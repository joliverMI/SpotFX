import logging

import numpy as np
import voluptuous as vol

import fx.effects.particle_handoff as particle_handoff
from fx.color import validate_gradient
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect

_LOGGER = logging.getLogger(__name__)

CAP = 96            # particle buffer cap (2 per firework)
SUBSTEPS = 3        # path sub-samples per frame (gap-free smear)
DT_MAX = 0.1
FADE_IN_S = 0.05
KERNEL_MAX = 8      # max blob radius in pixels

# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; see _phase_step). Same arc as 2D Fireworks: launch
# rate climbs while pairs shrink; the lull goes dark except two slow
# rockets crossing from the strip ends past the middle, dimming with
# trails; the drop explodes each into giant pairs in its own color.
CHARGE_SPAWN_X = 5.0
CHARGE_SLOW = 0.55
CHARGE_SHORT = 0.4
LULL_ROCKETS = 2
LULL_FLIGHT_S = 4.0
LULL_ROCKET_FADE = 0.75
DROP_SETTLE_S = 0.9
PAYOFF_SPEED = 1.8
PAYOFF_LIFE = 1.5


class Fireworks1d(AudioReactiveEffect, GradientEffect):
    """Fireworks flattened onto a strip: each firework spawns TWO particles
    at a random position that race away from each other, trailing and
    fading as they go (like a removed Orbits Strip particle). Both share
    one color, picked at random from the gradient per firework. Volume
    drives brightness and launch speed; spawn pacing mirrors the 2D
    Fireworks (spawn_rate + beat_burst + spawn_audio, capped by max_blobs).
    Positions wrap, so connected-end strips read as a true ring. No
    center weighting — origins are uniform along the strip.
    """

    NAME = "Fireworks Strip"
    CATEGORY = "Classic"
    HIDDEN_KEYS = ["gradient_roll", "color_blend"]
    # phase/phase_progress are SpotFX-driven choreography; advanced (not
    # hidden) so the arc can be hand-scrubbed in the LedFX UI for tuning.
    # burst_rockets is the same kind of key (SpotFX's firework_burst flare
    # drives it; self-resets after firing).
    ADVANCED_KEYS = AudioReactiveEffect.ADVANCED_KEYS + [
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
                description="Implode: the pair races TOWARD each other, brightening into the meeting point",
                default=False,
            ): bool,
            vol.Optional(
                "burst_speed",
                description="Base separation speed, as a fraction of the strip per second",
                default=0.35,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=1.5)),
            vol.Optional(
                "burst_life",
                description="Seconds a particle lives after the launch",
                default=1.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.3, max=3.0)),
            vol.Optional(
                "drag",
                description="How hard particles decelerate after the launch",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "speed_audio",
                description="How much the music boosts the separation speed",
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
                default=24,
            ): vol.All(vol.Coerce(int), vol.Range(min=4, max=96)),
            vol.Optional(
                "blob_size",
                description="Particle radius in pixels",
                default=1.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=6.0)),
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
                description="Payoff rockets to explode right now (driven by SpotFX flares; self-resets)",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=12)),
        }
    )

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        self.f_pos = np.zeros(CAP, dtype=np.float32)   # strip fraction
        self.f_vel = np.zeros(CAP, dtype=np.float32)   # fraction / s
        self.f_age = np.zeros(CAP, dtype=np.float32)
        self.f_life = np.full(CAP, 1.0, dtype=np.float32)
        self.f_grad = np.zeros(CAP, dtype=np.float32)
        self.f_bright = np.zeros(CAP, dtype=np.float32)
        self.f_pos0 = np.full(CAP, np.nan, dtype=np.float32)
        # 1 = reverse-spawned (imploding, runs its brightness curve backward)
        self.f_rev = np.zeros(CAP, dtype=np.float32)
        # 1 = lull rocket (position guided each frame; see _phase_rockets)
        self.f_rocket = np.zeros(CAP, dtype=np.float32)
        self.n = 0
        self.spawn_acc = 0.0
        self.impulse = 0.0
        self._beat_pending = False
        self._rng = np.random.default_rng()
        self.trail = None

    def config_updated(self, config):
        super().config_updated(config)
        self.spawn_rate = self._config["spawn_rate"]
        self.beat_burst = int(self._config["beat_burst"])
        self.spawn_audio = self._config["spawn_audio"]
        self.reverse = self._config["reverse"]
        self.burst_speed = self._config["burst_speed"]
        self.burst_life = self._config["burst_life"]
        self.drag = self._config["drag"]
        self.speed_audio = self._config["speed_audio"]
        self.brightness_audio = self._config["brightness_audio"]
        self.max_blobs = int(self._config["max_blobs"])
        self.blob_size = self._config["blob_size"]
        self.trail_decay = self._config["trail_decay"]

        self.power_func = self.POWER_FUNCS_MAPPING[
            self._config["frequency_range"]
        ]
        self.impulse_filter = self.create_filter(
            alpha_decay=self._config["impulse_decay"], alpha_rise=0.99
        )

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
            self._rocket_path = None
            self._pspawn = 1.0
            self._pspeed = 1.0
            self._plife = 1.0
            self._phase_done_t = None
        else:
            # non-creation pass: a changed phase key arms the edge
            self._phase_pending = new_phase if new_phase != self._phase else None

        # flare-driven payoff burst: edge-detect burst_rockets exactly like
        # the phase key (SpotFX writes a count, render consumes it and
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

    def on_activate(self, pixel_count):
        if self.trail is None or len(self.trail) != pixel_count:
            self.trail = np.zeros((pixel_count, 3), dtype=np.float32)

    def _compact(self, alive):
        count = int(np.count_nonzero(alive))
        for arr in (
            self.f_pos, self.f_vel, self.f_age, self.f_life,
            self.f_grad, self.f_bright, self.f_pos0, self.f_rev,
            self.f_rocket,
        ):
            arr[:count] = arr[: self.n][alive]
        self.n = count

    def _spawn_firework(self, pos=None, grad=None, bright=None,
                        speed_mult=1.0, life_mult=1.0, ignore_cap=False):
        """Two particles from one point, racing apart, one color.
        ignore_cap bypasses max_blobs (the drop payoff must always land)."""
        room = CAP if ignore_cap else min(self.max_blobs, CAP)
        if room - self.n < 2:
            return
        rng = self._rng
        if pos is None:
            pos = rng.random()
        if grad is None:
            grad = rng.random()
        if bright is None:
            bright = float(
                np.clip(0.45 + self.brightness_audio * self.impulse, 0.2, 1.0)
            )
        speed = (
            self.burst_speed
            * speed_mult
            * self._pspeed
            * (1.0 + self.speed_audio * min(self.impulse, 1.0))
            * rng.uniform(0.7, 1.15)
        )
        s = slice(self.n, self.n + 2)
        lives = (
            self.burst_life * life_mult * self._plife
            * rng.uniform(0.8, 1.15, 2)
        )
        if self.reverse:
            # implosion: start each particle out at the distance its
            # drag-decelerated run covers over its life, racing inward —
            # the pair meets at `pos` right as it fades out
            hl = max(0.6 - 0.5 * self.drag, 0.05)
            dist = speed * (hl / np.log(2)) * (
                1.0 - np.power(2.0, -lives / hl)
            )
            self.f_pos[s] = (pos + np.array((dist[0], -dist[1]))) % 1.0
            self.f_vel[s] = (-speed, speed)
        else:
            self.f_pos[s] = pos
            self.f_vel[s] = (speed, -speed)
        self.f_age[s] = 0.0
        self.f_life[s] = lives
        self.f_grad[s] = grad
        self.f_bright[s] = bright
        self.f_pos0[s] = self.f_pos[s]
        self.f_rev[s] = 1.0 if self.reverse else 0.0
        self.f_rocket[s] = 0.0
        self.n += 2

    # ── charge/lull/drop choreography ───────────────────────────────────

    def _launch_rockets(self):
        if CAP - self.n < LULL_ROCKETS:
            return
        rng = self._rng
        # from near the strip ends toward offset points past the middle
        starts = np.array([0.03, 0.97], dtype=np.float32)[:LULL_ROCKETS]
        ends = np.array([
            0.5 + rng.uniform(0.05, 0.14),
            0.5 - rng.uniform(0.05, 0.14),
        ], dtype=np.float32)[:LULL_ROCKETS]
        s = slice(self.n, self.n + LULL_ROCKETS)
        self.f_pos[s] = starts
        self.f_vel[s] = 0.0
        self.f_age[s] = 0.0
        self.f_life[s] = 1e6  # guided: never age out
        self.f_grad[s] = rng.random(LULL_ROCKETS, dtype=np.float32)
        self.f_bright[s] = 1.0
        self.f_pos0[s] = starts
        self.f_rev[s] = 0.0
        self.f_rocket[s] = 1.0
        self.n += LULL_ROCKETS
        self._rocket_path = {"s": starts.copy(), "e": ends.copy()}

    def _phase_rockets(self):
        path = self._rocket_path
        if path is None:
            return
        n = self.n
        idx = np.flatnonzero(self.f_rocket[:n] > 0.0)
        m = min(idx.size, len(path["s"]))
        if m <= 0:
            return
        idx = idx[:m]
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        f = p if p > 0.0 else min(self._phase_t / LULL_FLIGHT_S, 1.0)
        ease = 1.0 - (1.0 - f) ** 2
        self.f_pos[idx] = path["s"][:m] + (path["e"][:m] - path["s"][:m]) * ease
        self.f_bright[idx] = 1.0 - LULL_ROCKET_FADE * f

    def _rocket_payoff(self):
        n = self.n
        idx = np.flatnonzero(self.f_rocket[:n] > 0.0)
        if idx.size:
            origins = [
                (float(self.f_pos[i]), float(self.f_grad[i])) for i in idx
            ]
            self.f_life[idx] = 0.0  # rockets die into their explosions
        else:
            rng = self._rng
            origins = [
                (float(rng.uniform(0.3, 0.7)), float(rng.random()))
                for _ in range(LULL_ROCKETS)
            ]
        for pos, grad in origins:
            self._payoff_burst_at(pos, grad)
        self._rocket_path = None

    def _payoff_burst_at(self, pos, grad):
        """Two staggered pairs from one origin = a fat, layered burst —
        the drop payoff's own spawn shape, shared verbatim by the
        flare-driven burst (_flare_burst) so the two can never drift."""
        self._spawn_firework(pos=pos, grad=grad, bright=1.0,
                             speed_mult=PAYOFF_SPEED,
                             life_mult=PAYOFF_LIFE, ignore_cap=True)
        self._spawn_firework(pos=pos, grad=grad, bright=1.0,
                             speed_mult=PAYOFF_SPEED * 0.6,
                             life_mult=PAYOFF_LIFE, ignore_cap=True)

    def _flare_burst(self, count):
        """`count` payoff rockets explode NOW — the flare-driven burst
        (burst_rockets, written by SpotFX's firework_burst flare kind).
        Each origin gets _rocket_payoff's own layered pair-of-pairs at a
        uniform strip position like an ordinary launch — purely additive
        on top of whatever is already flying (ignore_cap, and no live
        particle, rocket, or phase state is touched)."""
        rng = self._rng
        for _ in range(count):
            self._payoff_burst_at(float(rng.random()), float(rng.random()))

    def _phase_step(self, dt):
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
                elif pend == "none" and prev == "lull":
                    n = self.n
                    idx = np.flatnonzero(self.f_rocket[:n] > 0.0)
                    if idx.size:
                        self.f_life[idx] = self.f_age[idx] + 0.4
                    self._rocket_path = None
        self._pspawn = 1.0
        self._pspeed = 1.0
        self._plife = 1.0
        if self._phase == "none":
            return
        self._phase_t += dt
        # orphan watchdog: a charge/lull whose payoff never arrives
        # releases itself — the rockets burn out, launching resumes
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self.phase_progress, self._phase_t,
            self._phase_done_t,
        )
        if due:
            _LOGGER.info(
                "fireworks1d: %s watchdog release after %.1fs",
                self._phase, self._phase_t,
            )
            n = self.n
            idx = np.flatnonzero(self.f_rocket[:n] > 0.0)
            if idx.size:
                self.f_life[idx] = self.f_age[idx] + 0.4
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
            self._pspeed = 1.0 - CHARGE_SLOW * p
            self._plife = 1.0 - CHARGE_SHORT * p
        elif self._phase == "drop":
            if self._phase_t >= DROP_SETTLE_S:
                self._phase = "none"
                self._apply_config(
                    {"phase": "none", "phase_progress": 0.0},
                    validate=False,
                    fire_event=False,
                )

    def _stamp(self, positions, rgb, size):
        """Additive 1D stamp of one sprite's substep path (wrap-aware)."""
        pixel_count = len(self.trail)
        pi = np.round(positions * pixel_count).astype(np.int64)
        k_span = int(np.ceil(size))
        k_off = np.arange(-k_span, k_span + 1, dtype=np.int64)
        k_w = np.clip(
            1.0 - np.abs(k_off) / (size + 0.5), 0.0, 1.0
        ).astype(np.float32)
        keep = k_w > 0.0
        k_off = k_off[keep]
        k_w = k_w[keep]
        idx = ((pi[:, None] + k_off[None, :]) % pixel_count).ravel()
        w = np.broadcast_to(
            k_w[None, :], (pi.size, k_w.size)
        ).ravel() / np.float32(pi.size)
        for channel in range(3):
            self._frame[:, channel] += np.bincount(
                idx, weights=w * rgb[channel], minlength=pixel_count
            )

    def render(self):
        pixel_count = self.pixel_count
        if self.trail is None or len(self.trail) != pixel_count:
            self.trail = np.zeros((pixel_count, 3), dtype=np.float32)

        dt = min(self.passed, DT_MAX)
        if not np.isfinite(dt) or dt <= 0:
            dt = 1.0 / 60.0
        if not np.isfinite(self.spawn_acc):
            self.spawn_acc = 0.0

        self._phase_step(dt)

        n = self.n
        # ── update ──────────────────────────────────────────────────────
        if n:
            self.f_pos0[:n] = self.f_pos[:n]
            self.f_pos[:n] = (self.f_pos[:n] + self.f_vel[:n] * dt) % 1.0
            hl = 0.6 - 0.5 * self.drag
            self.f_vel[:n] *= np.float32(0.5 ** (dt / max(hl, 0.05)))
            self.f_age[:n] += dt
            alive = self.f_age[:n] < self.f_life[:n]
            if not alive.all():
                self._compact(alive)
                n = self.n

        if self._phase == "lull":
            # guided rocket motion (positions set directly; f_pos0 above
            # gives them their motion smear + trail)
            self._phase_rockets()

        # ── spawn ───────────────────────────────────────────────────────
        # paused during a lull: the dark strip belongs to the rockets
        if self._phase != "lull":
            rate = self.spawn_rate * self._pspawn * (
                1.0 + self.spawn_audio * self.impulse * 3.0
            )
            self.spawn_acc += rate * dt
            bursts = int(self.spawn_acc)
            self.spawn_acc -= bursts
            if self._beat_pending:
                bursts += self.beat_burst
                self._beat_pending = False
            for _ in range(bursts):
                self._spawn_firework()
        else:
            self._beat_pending = False

        # flare-driven payoff burst — deliberately NOT gated on the lull
        # (a flare during a lull still lands, exactly as the drop payoff
        # itself does); self-reset re-arms the edge for the next write.
        # A stale persisted count on a fresh instance (nonzero _burst_seen
        # with nothing pending — the creation baseline armed no spawn) is
        # reset the same way, so the key reads 0 whenever idle and an
        # identical later write still edges.
        if self._burst_pending or self._burst_seen:
            pending = self._burst_pending
            self._burst_pending = 0
            if pending:
                self._flare_burst(pending)
            self._apply_config(
                {"burst_rockets": 0}, validate=False, fire_event=False
            )
        n = self.n

        # ── render ──────────────────────────────────────────────────────
        half_life = 0.02 + self.trail_decay * 0.5
        self.trail *= np.float32(0.5 ** (dt / half_life))

        if n:
            frac_t = np.clip(self.f_age[:n] / self.f_life[:n], 0.0, 1.0)
            fwd = (
                (1.0 - frac_t) ** 1.4
            ) * np.minimum(self.f_age[:n] / FADE_IN_S + 0.3, 1.0)
            # reverse envelope — mirror of the explosion: born with a
            # visible bias out wide, brightening into the meet, then a
            # fast terminal wink-out (no lingering blob). Trail Length
            # shapes the START: long trails = fainter, more gradual lead-in.
            start_bias = 0.2 + 0.3 * (1.0 - self.trail_decay)
            gamma = 0.8 + 1.2 * self.trail_decay
            rev_env = (
                start_bias + (1.0 - start_bias) * frac_t**gamma
            ) * np.clip((1.0 - frac_t) / 0.12, 0.0, 1.0) ** 0.7
            fade = np.where(self.f_rev[:n] > 0.0, rev_env, fwd)
            rgb = self.get_gradient_color_vectorized1d(
                self.f_grad[:n]
            ).astype(np.float32)

            fractions = (
                np.arange(1, SUBSTEPS + 1, dtype=np.float32) / SUBSTEPS
            )
            delta = (self.f_pos[:n] - self.f_pos0[:n] + 0.5) % 1.0 - 0.5
            paths = (
                self.f_pos0[:n][:, None] + delta[:, None] * fractions
            ) % 1.0

            size = float(
                np.clip(self.blob_size, 0.5, float(KERNEL_MAX))
            )
            self._frame = np.zeros((pixel_count, 3), dtype=np.float32)
            for i in range(n):
                b = fade[i] * self.f_bright[i]
                if b <= 0.0:
                    continue
                self._stamp(paths[i], rgb[i] * b, size)
            np.maximum(
                self.trail, np.minimum(self._frame, 255.0), out=self.trail
            )

        self.pixels = self.trail.copy()
