import logging

import numpy as np
import voluptuous as vol

import fx.effects.particle_handoff as particle_handoff
from fx.color import validate_gradient
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect

_LOGGER = logging.getLogger(__name__)

CAP = 1024          # particle capacity; overflow spawns are dropped
SUBSTEPS = 4        # path sub-samples per frame (gap-free smear)
R_FLOOR = 0.06      # radius floor for angular-velocity calc
# Angular motion reads ~4x bigger on a strip than on a small matrix (a
# revolution is the WHOLE strip), so the swirl→drift coupling is scaled way
# down and omega capped tighter than the 2D effect's 6π.
SWIRL_DRIFT = 0.3
OMEGA_MAX = 1.5 * np.pi
DT_MAX = 0.1
FADE_IN_S = 0.15
RING_BASE = 0.35    # sample-ring radius at radius_scale 1.0
VIS_SIGMAS = 3.3    # blobs live within this many envelope sigmas of the ring
CENTER_FADE_R = 0.12  # extra fade as falling blobs near the center
BAND_ANCHORS = np.array([0.0, 1 / 3, 2 / 3], dtype=np.float32)
BAND_JITTER = 0.06

# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; see _phase_step). Strip translation of the 2D arc:
# the growing event horizon sweeps a brightening white halo THROUGH the
# sample ring, then swallows it — the strip dims to black behind the
# flash. The lull holds black with a phosphor dot; the drop sweeps back
# and erupts a burst of blobs through the ring.
CHARGE_HALO_LEAD = 1.4  # halo growth vs the swallowing disc
DROP_FALLBACK_S = 0.45  # drop completes on this timer if no progress ramp
DROP_RESET_S = 0.5      # post-burst ease of the strip back to life
PHASE_BURST_N = 12      # blobs in the drop explosion


class Blackhole1d(AudioReactiveEffect, GradientEffect):
    """The 2D Blackhole seen through a 1 px ring stretched into a strip.

    Blobs keep the same polar physics (radial infall/eruption + swirl); the
    strip shows each blob at its angle, with brightness following a Gaussian
    of its radial distance to the sample ring — so a blob brightens as it
    approaches, peaks passing through, and trails away. Position wraps, so
    circular (connected-end) strips read as a true ring.
    """

    NAME = "Blackhole Strip"
    CATEGORY = "Classic"
    # color_spin supersedes gradient_roll for this effect
    HIDDEN_KEYS = ["gradient_roll"]
    # phase/phase_progress are SpotFX-driven choreography; advanced (not
    # hidden) so the arc can be hand-scrubbed in the LedFX UI for tuning.
    ADVANCED_KEYS = AudioReactiveEffect.ADVANCED_KEYS + [
        "accel",
        "edge_speed",
        "approach_width",
        "impulse_decay",
        "phase",
        "phase_progress",
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
                description="Swirl amount; sign sets direction, 0 = straight infall (blobs bloom in place)",
                default=3.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-6.0, max=6.0)),
            vol.Optional(
                "reverse",
                description="Blobs erupt from the center out through the ring",
                default=True,
            ): bool,
            vol.Optional(
                "radius_scale",
                description="Sample-ring radius scale: where along the fall blobs peak",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=2.0)),
            vol.Optional(
                "x_offset",
                description="Rotate the whole pattern around the strip",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "blob_size",
                description="Blob radius in pixels along the strip",
                default=1.5,
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
                "approach_width",
                description="Radial width of the approach/pass/trail brightness envelope",
                default=0.16,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=0.5)),
            vol.Optional(
                "trail_decay",
                description="Comet-trail length: 0 = crisp dots, 1 = long smear",
                default=0.3,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "color_mode",
                description="wheel: gradient wraps the strip and spins with gradient_spin; band: audio bands pick position; random: uniform (spin invisible)",
                default="wheel",
            ): vol.In(["wheel", "band", "random"]),
            vol.Optional(
                "gradient_spin",
                description="Baseline rotation of the whole pattern (rev/s); direction follows the swirl",
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
        # Particle SoA + accumulators live here (NOT on_activate) so they
        # survive config patches without killing all particles.
        self.p_r = np.zeros(CAP, dtype=np.float32)
        self.p_theta = np.zeros(CAP, dtype=np.float32)
        self.p_grad = np.zeros(CAP, dtype=np.float32)
        self.p_bright = np.zeros(CAP, dtype=np.float32)
        self.p_age = np.zeros(CAP, dtype=np.float32)
        self.n = 0
        self.spawn_acc = 0.0
        self.spin_total = 0.0
        self._beat_pending = False
        self.impulse = 0.0
        self.band_powers = np.zeros(3, dtype=np.float32)
        self._rng = np.random.default_rng()
        self.trail = None

    def config_updated(self, config):
        super().config_updated(config)
        self.swirl = self._config["swirl"]
        self.reverse = self._config["reverse"]
        self.radius_scale = self._config["radius_scale"]
        self.x_offset = self._config["x_offset"]
        self.blob_size = self._config["blob_size"]
        self.spawn_rate = self._config["spawn_rate"]
        self.beat_burst = int(self._config["beat_burst"])
        self.base_speed = self._config["base_speed"]
        self.accel = self._config["accel"]
        self.edge_speed = self._config["edge_speed"]
        self.max_blobs = int(self._config["max_blobs"])
        self.sigma = self._config["approach_width"]
        self.trail_decay = self._config["trail_decay"]
        self.color_mode = self._config["color_mode"]
        self.gradient_spin = self._config["gradient_spin"]
        self.spawn_audio = self._config["spawn_audio"]
        self.speed_audio = self._config["speed_audio"]

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

        # charge/lull/drop: edge-detect the phase key. State is created here
        # (not __init__) because config_updated runs first, during
        # super().__init__; the pending flag is consumed in render.
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

    def on_activate(self, pixel_count):
        if self.trail is None or len(self.trail) != pixel_count:
            self.trail = np.zeros((pixel_count, 3), dtype=np.float32)

    def _ring_radius(self):
        return float(np.clip(RING_BASE * self.radius_scale, 0.05, 0.95))

    def _bounds(self, ring):
        """(inner, outer) radial bounds of the visible envelope band."""
        span = VIS_SIGMAS * self.sigma
        return max(0.02, ring - span), min(1.05, ring + span)

    def _compact(self, alive):
        count = int(np.count_nonzero(alive))
        for arr in (
            self.p_r,
            self.p_theta,
            self.p_grad,
            self.p_bright,
            self.p_age,
        ):
            arr[:count] = arr[: self.n][alive]
        self.n = count

    def _spawn(self, count, beat_count, ring):
        # max_blobs is the user-facing density cap; CAP is the hard buffer
        # cap. int(): morph smoothing can hand us float counts.
        count = int(min(count, self.max_blobs - self.n, CAP - self.n))
        if count <= 0:
            return
        s = slice(self.n, self.n + count)
        rng = self._rng
        inner, outer = self._bounds(ring)
        if self.reverse:
            # erupt from just inside the visible band
            self.p_r[s] = rng.uniform(inner, inner + 0.03, count)
        else:
            # fall in from just outside it
            self.p_r[s] = rng.uniform(outer - 0.03, outer, count)
        self.p_theta[s] = rng.uniform(0.0, 2 * np.pi, count)
        self.p_age[s] = 0.0

        if self.color_mode == "band":
            weights = self.band_powers + 0.05
            weights = weights / weights.sum()
            bands = rng.choice(3, size=count, p=weights)
            self.p_grad[s] = (
                BAND_ANCHORS[bands]
                + rng.uniform(-BAND_JITTER, BAND_JITTER, count).astype(
                    np.float32
                )
            ) % 1.0
            self.p_bright[s] = 0.6 + 0.4 * self.band_powers[bands]
        elif self.color_mode == "wheel":
            # Gradient wrapped around the strip: blobs sample by spawn angle,
            # so the pattern rotation (gradient_spin) reads as moving colors.
            self.p_grad[s] = (
                self.p_theta[s] / (2 * np.pi)
                + rng.uniform(-0.04, 0.04, count).astype(np.float32)
            ) % 1.0
            self.p_bright[s] = rng.uniform(0.7, 1.0, count)
        else:  # random — pure uniform
            self.p_grad[s] = rng.random(count, dtype=np.float32)
            self.p_bright[s] = rng.uniform(0.6, 1.0, count)

        if beat_count > 0:
            self.p_bright[self.n + count - beat_count : self.n + count] = 1.0
        self.n += count

    # ── charge/lull/drop choreography ───────────────────────────────────
    # SpotFX writes `phase` (instant) and ramps `phase_progress` 0→1 over
    # the event's ramp. See the module constants for the strip translation.

    def _enter_phase(self, phase):
        self._phase = phase
        self._phase_t = 0.0
        self._phase_done_t = None
        if phase == "charge":
            self._drop = None
            # charge always falls inward; remember the configured direction
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
            self._apply_config(dict(saved), validate=False, fire_event=False)

    def _phase_burst(self, ring):
        """Drop payoff: a guaranteed burst of full-bright blobs spawned for
        the restored flow direction (bypasses max_blobs)."""
        saved_max = self.max_blobs
        self.max_blobs = CAP
        try:
            self._spawn(PHASE_BURST_N, PHASE_BURST_N, ring)
        finally:
            self.max_blobs = saved_max

    def _phase_step(self, dt, ring):
        pend = self._phase_pending
        if pend is not None:
            self._phase_pending = None
            if pend != self._phase:
                self._enter_phase(pend)
        if self._phase == "none":
            return
        self._phase_t += dt
        # orphan watchdog: a charge/lull whose payoff never arrives
        # releases itself as a silent drop (sweep back, no burst)
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self.phase_progress, self._phase_t,
            self._phase_done_t,
        )
        if due:
            _LOGGER.info(
                "blackhole1d: %s watchdog release after %.1fs",
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
                p = max(
                    self.phase_progress,
                    min(self._phase_t / DROP_FALLBACK_S, 1.0),
                )
                if p >= 0.995:
                    drop["burst_t"] = 0.0
                    self._restore_phase_overrides()
                    if not drop.get("silent"):
                        self._phase_burst(ring)
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

    def _phase_post(self, out, ring, outer):
        """Post-process the strip for the active phase: the swallow mask +
        traveling halo flash (charge/drop), the black hold + phosphor dot
        (lull)."""
        phase = self._phase
        if phase == "none":
            return out
        pixel_count = len(out)
        top = outer + 0.05
        mask = 1.0
        halo_r = None
        halo_g = 0.0
        if phase == "charge":
            p = float(np.clip(self.phase_progress, 0.0, 1.0))
            halo_r = min(CHARGE_HALO_LEAD * p * p, 1.0) * top
            disc_r = p * p * top
            mask = float(np.clip((ring + 0.04 - disc_r) / 0.12, 0.0, 1.0))
            halo_g = 0.25 + 0.75 * p
        elif phase == "lull":
            mask = 0.0
        else:  # drop
            drop = self._drop
            if drop is not None and drop["burst_t"] is not None:
                mask = float(min(drop["burst_t"] / DROP_RESET_S, 1.0))
            else:
                p = max(
                    self.phase_progress,
                    min(self._phase_t / DROP_FALLBACK_S, 1.0),
                )
                halo_r = ((1.0 - p) ** 2) * top
                disc_r = halo_r
                mask = float(np.clip((ring + 0.04 - disc_r) / 0.12, 0.0, 1.0))
                halo_g = 1.0
        out = out * np.float32(mask)
        if halo_r is not None and halo_g > 0.0:
            # halo flash as the horizon crosses the sample ring — brighter
            # and wider as the charge builds
            gw = 0.05 + 0.10 * halo_g
            g = float(np.exp(-0.5 * ((halo_r - ring) / gw) ** 2)) * halo_g
            if g > 0.003:
                out = np.minimum(out + np.float32(g * 235.0), 255.0)
        if phase == "lull":
            # lingering phosphor dot at the strip middle
            mid = pixel_count // 2
            out[max(mid - 1, 0): mid + 2] = np.maximum(
                out[max(mid - 1, 0): mid + 2], 70.0
            )
        return out

    def render(self):
        pixel_count = self.pixel_count
        if self.trail is None or len(self.trail) != pixel_count:
            self.trail = np.zeros((pixel_count, 3), dtype=np.float32)

        dt = min(self.passed, DT_MAX)
        if not np.isfinite(dt) or dt <= 0:
            dt = 1.0 / 60.0
        if not np.isfinite(self.spawn_acc):
            self.spawn_acc = 0.0
        if not np.isfinite(self.spin_total):
            self.spin_total = 0.0

        ring = self._ring_radius()
        inner, outer = self._bounds(ring)
        swirl_sign = np.sign(self.swirl) if self.swirl != 0 else 1.0

        self._phase_step(dt, ring)

        n = self.n
        # ── update ──────────────────────────────────────────────────────
        if n:
            r = self.p_r[:n]
            r0 = r.copy()
            th0 = self.p_theta[:n].copy()
            v = self.base_speed * (
                self.edge_speed
                + (1.0 - self.edge_speed)
                * np.clip(1.0 - r, 0.0, 1.0) ** self.accel
            )
            v = v * (1.0 + self.speed_audio * self.impulse * 2.0)
            omega = np.clip(
                self.swirl * SWIRL_DRIFT * v / np.maximum(r, R_FLOOR),
                -OMEGA_MAX,
                OMEGA_MAX,
            )
            self.p_r[:n] = r + (v if self.reverse else -v) * dt
            self.p_theta[:n] = th0 + omega * dt
            self.p_age[:n] += dt

            # blobs die once they leave the visible envelope band
            if self.reverse:
                alive = self.p_r[:n] < outer
            else:
                alive = self.p_r[:n] > inner
            keep_r0 = r0[alive]
            keep_th0 = th0[alive]
            self._compact(alive)
            r0, th0 = keep_r0, keep_th0
            n = self.n

        # ── spawn ───────────────────────────────────────────────────────
        # paused during the lull: the strip is black, blobs would be unseen
        rate = 0.0 if self._phase == "lull" else self.spawn_rate * (
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
        # Baseline pattern rotation follows the swirl direction.
        self.spin_total = (
            self.spin_total + self.gradient_spin * swirl_sign * dt
        ) % 1.0
        prev_n = self.n
        self._spawn(n_new, beat_count, ring)
        if self.n > prev_n:
            # Fresh spawns render as stationary points this frame
            fresh = slice(prev_n, self.n)
            if prev_n:
                r0 = np.concatenate([r0, self.p_r[fresh]])
                th0 = np.concatenate([th0, self.p_theta[fresh]])
            else:
                r0 = self.p_r[fresh].copy()
                th0 = self.p_theta[fresh].copy()
        n = self.n

        # ── render ──────────────────────────────────────────────────────
        half_life = 0.02 + self.trail_decay * 0.5
        self.trail *= np.float32(0.5 ** (dt / half_life))

        if n:
            rgb = self.get_gradient_color_vectorized1d(
                self.p_grad[:n]
            ).astype(np.float32)
            fade = np.minimum(self.p_age[:n] / FADE_IN_S, 1.0)
            rgb *= (self.p_bright[:n] * fade)[:, None]

            # Sub-sample each blob's path this frame; per-substep the
            # radial Gaussian envelope sets how bright the pass reads.
            fractions = (
                np.arange(1, SUBSTEPS + 1, dtype=np.float32) / SUBSTEPS
            )
            ri = r0[:, None] + (self.p_r[:n] - r0)[:, None] * fractions
            thi = th0[:, None] + (self.p_theta[:n] - th0)[:, None] * fractions
            env = np.exp(
                -0.5 * ((ri - ring) / max(self.sigma, 1e-3)) ** 2
            ).astype(np.float32)
            if not self.reverse:
                # extra fade as falling blobs near the center, so deaths at
                # the inner bound never pop
                env *= np.clip(ri / CENTER_FADE_R, 0.0, 1.0)

            shift = self.spin_total + (self.x_offset - 0.5)
            pos = (thi / (2 * np.pi) + shift) % 1.0
            pi = np.round(pos * pixel_count).astype(np.int64)

            k_span = int(np.ceil(self.blob_size))
            k_off = np.arange(-k_span, k_span + 1, dtype=np.int64)
            k_w = np.clip(
                1.0 - np.abs(k_off) / (self.blob_size + 0.5), 0.0, 1.0
            ).astype(np.float32)
            keep = k_w > 0.0
            k_off = k_off[keep]
            k_w = k_w[keep]

            # (blob, substep, kernel) → wrapped pixel index
            idx = (pi[:, :, None] + k_off[None, None, :]) % pixel_count
            idx = idx.ravel()
            weight = (env[:, :, None] * k_w[None, None, :]).ravel()
            frame = np.zeros_like(self.trail)
            inv = np.float32(1.0 / SUBSTEPS)
            for channel in range(3):
                vals = (
                    np.repeat(rgb[:, channel] * inv, SUBSTEPS * k_off.size)
                    * weight
                )
                frame[:, channel] = np.bincount(
                    idx, weights=vals, minlength=pixel_count
                )
            # Bright current blobs over a fading history, bounded.
            np.maximum(self.trail, np.minimum(frame, 255.0), out=self.trail)

            self.p_theta[:n] %= 2 * np.pi

        self.pixels = self._phase_post(self.trail.copy(), ring, outer)
