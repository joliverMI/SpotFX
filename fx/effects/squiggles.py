"""Squiggles — wriggling LED chains that fly straight across the matrix.

Fitted to the crystal ball's physical lattice: live LEDs sit on a
checkerboard (column parity alternates per row) inside an elliptical
silhouette, so chains walk the DEVICE lattice — diagonal LED-neighbor
moves plus vertical two-row moves, six directed orientations with no
horizontal among them. Every vertex and every lit pixel of a chain is a
real LED; a step may turn only one slot (never straight through a vertex,
never reverse), and error-diffusion steering keeps the center of mass on a
straight line. Headings avoid a configurable buffer around horizontal.

Spawning mirrors Blackhole's pacing (spawn rate + beat bursts + audio
boost), but there is no attractor: chains are born ON the crystal's
silhouette edge with a few segments already laid inward (visible
immediately), aimed at the center +-30 degrees; they fly straight, leave
the silhouette and delete. Reverse flips travel: every live chain turns
around and retraces its path; new chains keep entering from the edge.

Collisions (head-on, > 90 degrees between headings) explode both chains
into a small firework of sparks; shallower contacts bounce elastically.

Step size and thickness can be jiggled per-chain like the Orbits effect.
Audio drives speed, chain length, brightness and spawn pacing.
"""

import logging
import math
from collections import deque

import numpy as np
import voluptuous as vol
from PIL import Image

import fx.effects.particle_handoff as particle_handoff
from fx.color import validate_gradient
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect
from fx.effects.twod import Twod

_LOGGER = logging.getLogger(__name__)

DT_MAX = 0.1
SPARK_CAP = 256
CHAIN_HARD_CAP = 64
FADE_IN_S = 0.25
COLLIDE_COOLDOWN_S = 0.45
COLLIDE_MIN_AGE_S = 0.35
SPARKS_PER_BOOM = 26
SPARK_LIFE_S = 0.9
SPARK_DRAG = 2.2  # 1/s velocity decay
KERNEL_R = 3  # spark splat kernel

START_SEGS = 3  # segments pre-laid inward at spawn (visible immediately)

# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; see _phase_step)
CHARGE_RATE = 7.0    # extra chains/s at full charge
CHARGE_MAX_X = 1.6   # max_chains growth factor at full charge
LULL_CRT_S = 2.2     # CRT collapse fallback when no lull ramp arrives
CRT_SPLIT = 0.55     # lull fraction where the vertical squash completes
DROP_BURST_N = 9     # chains erupting from the center on the drop
# The burst fires on the phase's first frame — drop anchors its START to
# the trigger mark (his ruling, 2026-08-20, superseding the end-anchored
# gate this effect used to mirror from Blackhole; see _phase_step's own
# comment for the full history and fx/effects/blackhole.py's matching
# change).
# Burst chains fly at this fraction of normal speed so the explosion
# lingers rather than flashing past — his ask "last longer" (2026-08-20,
# picked value, not measured against a reference; expect to retune).
DROP_BURST_SPEED_MULT = 0.55
DROP_SETTLE_S = 1.0  # post-burst settle before phase auto-reset (measured
                     # from the burst itself, not from phase entry)

# The device lattice (walkable live-LED graph, ring moves, silhouette,
# brush shells) comes from the shared lattice API — derived from the
# virtual's shape map when present, full-rect checkerboard fallback
# otherwise. A chain step may turn only +-1 ring slot — never straight,
# never reverse.
from fx.effects.lattice import AVG_MOVE_PX, RING, RING_ANGLES  # noqa: E402


def _wrap_pi(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class Squiggles2d(Twod, GradientEffect):
    NAME = "Squiggles"
    CATEGORY = "Matrix"
    # chains are painted pixel-exact on the device lattice — shape-mapped
    # virtuals must identity-sample this effect, never kernel-resample it
    LATTICE_EXACT = True
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + ["gradient_roll"]
    # phase/phase_progress are SpotFX-driven choreography; advanced (not
    # hidden) so the arc can be hand-scrubbed in the LedFX UI for tuning.
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "horizontal_gap",
        "impulse_decay",
        "phase",
        "phase_progress",
    ]

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "gradient",
                description="Chain color gradient",
                default="linear-gradient(90deg, #ff0000 0.00%,#ff7800 14.00%,#ffc800 28.00%,#00ff00 42.00%,#00c78c 56.00%,#0000ff 70.00%,#800080 84.00%,#ff00b2 98.00%)",
            ): validate_gradient,
            vol.Optional(
                "spawn_rate",
                description="Base chains spawned per second; 0 = beat bursts only",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=30.0)),
            vol.Optional(
                "beat_burst",
                description="Extra chains spawned on each beat",
                default=2,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=12)),
            vol.Optional(
                "spawn_audio",
                description="How much the selected band boosts the spawn rate",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "max_blobs",
                description="Density cap: spawning pauses at this many live chains",
                default=14,
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=CHAIN_HARD_CAP)),
            vol.Optional(
                "base_speed",
                description="Center-of-mass speed in pixels per second",
                default=38.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=2.0, max=60.0)),
            vol.Optional(
                "speed_audio",
                description="How much the selected band boosts the speed",
                default=2.7,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
            vol.Optional(
                "step_size",
                description="Hex edge length in pixels (the minimum step)",
                default=3,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
            vol.Optional(
                "step_count",
                description="Chain length in hex steps",
                default=4,
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=24)),
            vol.Optional(
                "length_audio",
                description="How much the selected band grows the chain length",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "blob_size",
                description="Chain thickness in pixels",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=6.0)),
            vol.Optional(
                "jiggle",
                description="0 = uniform chains; 1 = each chain wanders its own step size and thickness",
                default=0.24,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "horizontal_gap",
                description="Headings stay at least this many degrees away from horizontal",
                default=25.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=5.0, max=80.0)),
            vol.Optional(
                "brightness_audio",
                description="How much the selected band pumps chain brightness",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "reverse",
                description="Flip travel: every chain turns around and retraces its path",
                default=False,
            ): bool,
            vol.Optional(
                "x_offset",
                description="X offset for the flight center",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "y_offset",
                description="Y offset for the flight center",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "frequency_range",
                description="Audio band driving spawn/speed/length reactivity",
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
        # Chain + spark state lives here (NOT do_once) so it survives config
        # patches — morph ramps re-run do_once constantly.
        self.chains = []
        self.impulse = 0.0
        self._beat_pending = False
        self.spawn_acc = 0.0
        self._rng = np.random.default_rng()
        self._handoff_pending = True
        # held pacman adoption while its maze fades out (phase 1)
        self._pacman_hold = None
        # held radial adoption while the radial implodes (phase 1)
        self._radial_hold = None
        # squiggles→radial envoys: two chains that meet at the radial's
        # center and explode exactly at the bloom point
        self._envoys = None
        # spark SoA
        self.s_x = np.zeros(SPARK_CAP, dtype=np.float32)
        self.s_y = np.zeros(SPARK_CAP, dtype=np.float32)
        self.s_vx = np.zeros(SPARK_CAP, dtype=np.float32)
        self.s_vy = np.zeros(SPARK_CAP, dtype=np.float32)
        self.s_life = np.zeros(SPARK_CAP, dtype=np.float32)
        self.s_rgb = np.zeros((SPARK_CAP, 3), dtype=np.float32)
        self.s_n = 0
        # static spark splat kernel
        span = np.arange(-KERNEL_R, KERNEL_R + 1)
        kdx, kdy = np.meshgrid(span, span)
        kdist = np.sqrt(kdx**2 + kdy**2).ravel()
        keep = kdist <= KERNEL_R
        self.k_dx = kdx.ravel()[keep].astype(np.int32)
        self.k_dy = kdy.ravel()[keep].astype(np.int32)
        self.k_dist = kdist[keep].astype(np.float32)
        super().__init__(ledfx, config)

    def config_updated(self, config):
        super().config_updated(config)
        old_reverse = getattr(self, "reverse", None)
        self.spawn_rate = self._config["spawn_rate"]
        self.beat_burst = int(self._config["beat_burst"])
        self.spawn_audio = self._config["spawn_audio"]
        self.max_chains = int(self._config["max_blobs"])
        self.base_speed = self._config["base_speed"]
        self.speed_audio = self._config["speed_audio"]
        self.step_size = int(self._config["step_size"])
        self.step_count = int(self._config["step_count"])
        self.length_audio = self._config["length_audio"]
        self.blob_size = self._config["blob_size"]
        self.jiggle = self._config["jiggle"]
        self.gap_rad = math.radians(self._config["horizontal_gap"])
        self.brightness_audio = self._config["brightness_audio"]
        self.reverse = bool(self._config["reverse"])
        self.x_offset = self._config["x_offset"]
        self.y_offset = self._config["y_offset"]
        self.power_func = self.POWER_FUNCS_MAPPING[
            self._config["frequency_range"]
        ]
        self.impulse_filter = self.create_filter(
            alpha_decay=self._config["impulse_decay"], alpha_rise=0.99
        )
        if old_reverse is not None and old_reverse != self.reverse:
            for c in self.chains:
                self._turn_around(c)

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
            self._phase_rate = 0.0
            self._phase_done_t = None
            self._drop = None
        else:
            # non-creation pass: a changed phase key arms the edge
            self._phase_pending = new_phase if new_phase != self._phase else None

    def audio_data_updated(self, data):
        # audio thread — latch only
        impulse = self.impulse_filter.update(getattr(data, self.power_func)())
        self.impulse = float(impulse) if np.isfinite(impulse) else 0.0
        if data.bpm_beat_now():
            self._beat_pending = True

    def do_once(self):
        super().do_once()
        from fx.effects import lattice

        w, h = self.r_width, self.r_height
        self.cx = (w - 1) * self.x_offset
        self.cy = (h - 1) * self.y_offset
        self._n_cells = w * h
        # device lattice: real silhouette + boundary spawn pool from the
        # shape map (full-rect fallback elsewhere). The pool only contains
        # live LEDs — no phantom spawns on the gappy pole rows.
        self.lat = lattice.get_view(self)
        self._lo, self._hi = self.lat.row_extents()
        self._edge_pool = self.lat.edge_pool()

    def _snap_point(self, x, y):
        """Nearest live LED to an arbitrary float render point."""
        return self.lat.snap(x, y)

    def _inside(self, c, r):
        # silhouette-extent semantics (dead twins count as inside): chains
        # are judged gone once past the silhouette, not per-cell
        return self.lat.in_extent(c, r)

    # ── heading helpers ────────────────────────────────────────────────

    def _clamp_heading(self, theta):
        """Keep theta at least gap_rad away from the horizontal axis,
        preserving which vertical half-plane it points into."""
        theta = _wrap_pi(theta)
        # distance to the nearest horizontal direction (0 or pi)
        d0 = abs(_wrap_pi(theta))
        d180 = abs(_wrap_pi(theta - math.pi))
        if min(d0, d180) >= self.gap_rad:
            return theta
        up = math.sin(theta) >= 0.0
        if not up and math.sin(theta) == 0.0:
            up = bool(self._rng.random() < 0.5)
        base = 0.0 if d0 <= d180 else math.pi
        sign = 1.0 if up else -1.0
        # small random push past the boundary so clamped headings don't
        # all pile up at exactly the gap angle
        extra = float(self._rng.uniform(0.0, math.radians(8.0)))
        return _wrap_pi(base + sign * (self.gap_rad + extra))

    @staticmethod
    def _closest_slot(theta):
        return min(
            range(6), key=lambda i: abs(_wrap_pi(RING_ANGLES[i] - theta))
        )

    def _steer(self, c, seg_len=1):
        """Next hex slot: only +-60 deg turns. Error-diffusion steering —
        take the turn whose endpoint stays closest to the chain's ideal
        straight line — so the MEAN direction converges to theta for any
        heading (greedy nearest-angle would average out horizontal when
        theta sits between two hex directions). Jiggle occasionally takes
        the other turn; the error term pulls it back."""
        hx, hy = c["path"][-1]
        ux, uy = math.cos(c["theta"]), math.sin(c["theta"])
        p0x, p0y = c["p0"]
        a = (c["slot"] + 1) % 6
        b = (c["slot"] - 1) % 6

        def err(idx):
            # project the WHOLE planned segment, not one move — committing
            # several moves on a one-move estimate overshoots the line
            dc, dr = RING[idx]
            px, py = hx + dc * seg_len, hy + dr * seg_len
            return abs((px - p0x) * uy - (py - p0y) * ux)

        ea, eb = err(a), err(b)
        best, other = (a, b) if ea <= eb else (b, a)
        # jiggle may take the other turn, but never one that strays far
        # from the line — keeps the wander bounded, not a drunk walk
        if (
            self._rng.random() < self.jiggle * 0.25
            and abs(ea - eb) < 2.5
        ):
            return other
        return best

    # ── chain lifecycle ────────────────────────────────────────────────

    def _new_chain(self, pos, theta, grad=None, bright=1.0):
        theta = self._clamp_heading(theta)
        rng = self._rng
        j = self.jiggle
        return {
            "path": deque([self._snap_point(*pos)], maxlen=256),
            "theta": theta,
            "p0": pos,  # anchor of the ideal straight line
            "slot": self._closest_slot(theta),
            "seg_left": 0,  # lattice moves left in the current segment
            "acc": 0.0,  # fractional lattice-move accumulator
            "grad": float(rng.random()) if grad is None else float(grad),
            "bright": float(bright),
            "age": 0.0,
            "cooldown": 0.0,
            "step_mult": 1.0 + j * float(rng.uniform(-0.4, 0.9)),
            "thick_mult": 1.0 + j * float(rng.uniform(-0.5, 1.2)),
            "wander": float(rng.uniform(0.0, 2 * math.pi)),
            "last_turn": 0,
            "turn_run": 0,
        }

    def _seg_len(self, c):
        wob = 1.0 + self.jiggle * 0.35 * math.sin(c["wander"])
        return max(1, int(round(self.step_size * c["step_mult"] * wob)))

    def _walk_one(self, c):
        """Advance the head by ONE lattice move, turning one slot at
        segment boundaries."""
        if c["seg_left"] <= 0:
            c["wander"] += 0.6
            planned = self._seg_len(c)
            new_slot = self._steer(c, planned)
            turn = 1 if (new_slot - c["slot"]) % 6 == 1 else -1
            if turn == c["last_turn"]:
                c["turn_run"] += 1
                # never curl into a closed loop: after 3 same-way turns,
                # force the other one
                if c["turn_run"] > 3:
                    turn = -turn
                    new_slot = (c["slot"] + turn) % 6
                    c["turn_run"] = 1
            else:
                c["turn_run"] = 1
            c["last_turn"] = turn
            c["slot"] = new_slot
            c["seg_left"] = planned
        hx, hy = c["path"][-1]
        dc, dr = RING[c["slot"]]
        c["path"].append((hx + dc, hy + dr))
        c["seg_left"] -= 1

    def _trim(self, c, steps_target):
        body_moves = max(2, self.step_size * steps_target)
        while len(c["path"]) > body_moves + 1:
            c["path"].popleft()

    def _spawn(self, count):
        count = int(min(count, self.max_chains - len(self.chains)))
        rng = self._rng
        for _ in range(max(0, count)):
            jitter = math.radians(float(rng.uniform(-30.0, 30.0)))
            # born ON the crystal's silhouette edge, aimed at the center
            # (the diameter line) +- 30 degrees, with a few segments
            # already laid inward — visible immediately
            pos = self._edge_pool[int(rng.integers(len(self._edge_pool)))]
            theta = math.atan2(self.cy - pos[1], self.cx - pos[0]) + jitter
            c = self._new_chain(pos, theta)
            for _ in range(START_SEGS * max(1, self.step_size)):
                self._walk_one(c)
            self._trim(c, self.step_count)
            self.chains.append(c)

    def _turn_around(self, c):
        """Reverse toggled: the chain retraces its own body."""
        c["theta"] = self._clamp_heading(c["theta"] + math.pi)
        pts = list(c["path"])
        pts.reverse()
        c["path"] = deque(pts, maxlen=256)
        if len(pts) >= 2:
            dc = pts[-1][0] - pts[-2][0]
            dr = pts[-1][1] - pts[-2][1]
            try:
                c["slot"] = RING.index((dc, dr))
            except ValueError:
                c["slot"] = self._closest_slot(c["theta"])
        else:
            c["slot"] = self._closest_slot(c["theta"])
        c["seg_left"] = 0
        c["acc"] = 0.0
        c["p0"] = pts[-1]

    def _head_pos(self, c):
        hx, hy = c["path"][-1]
        return (float(hx), float(hy))

    def _steps_target(self):
        return int(
            min(
                24,
                max(
                    1,
                    round(
                        self.step_count
                        * (1.0 + self.length_audio * self.impulse)
                    ),
                ),
            )
        )

    def _advance_chain(self, c, dt, speed_px, steps_target):
        c["acc"] += (speed_px * dt) / AVG_MOVE_PX
        guard = 0
        while c["acc"] >= 1.0 and guard < 24:
            guard += 1
            c["acc"] -= 1.0
            self._walk_one(c)
        self._trim(c, steps_target)
        c["age"] += dt
        c["cooldown"] = max(0.0, c["cooldown"] - dt)

    def _offscreen(self, c):
        """Gone once every point has left the crystal silhouette — pixels
        past the edge are dead LEDs anyway."""
        if c["age"] < 0.6:
            return False
        return not any(self._inside(p[0], p[1]) for p in c["path"])

    # ── collisions ─────────────────────────────────────────────────────

    def _boom(self, pos, rgb_a, rgb_b):
        rng = self._rng
        k = min(SPARKS_PER_BOOM, SPARK_CAP - self.s_n)
        if k <= 0:
            return
        s = slice(self.s_n, self.s_n + k)
        ang = rng.uniform(0.0, 2 * math.pi, k).astype(np.float32)
        spd = rng.uniform(12.0, 42.0, k).astype(np.float32)
        self.s_x[s] = pos[0]
        self.s_y[s] = pos[1]
        self.s_vx[s] = np.cos(ang) * spd
        self.s_vy[s] = np.sin(ang) * spd
        self.s_life[s] = rng.uniform(0.45, SPARK_LIFE_S, k).astype(
            np.float32
        )
        half = k // 2
        rgb = np.empty((k, 3), dtype=np.float32)
        rgb[:half] = rgb_a
        rgb[half:] = rgb_b
        self.s_rgb[s] = rgb
        self.s_n += k

    def _collide(self, cols):
        """Head-vs-head collisions. Removes exploded chains and returns the
        color rows kept in sync with self.chains."""
        n = len(self.chains)
        if n < 2:
            return cols
        heads = [self._head_pos(c) for c in self.chains]
        dead = set()
        for i in range(n):
            ci = self.chains[i]
            if (
                i in dead
                or ci.get("envoy")
                or ci["cooldown"] > 0
                or ci["age"] < COLLIDE_MIN_AGE_S
            ):
                continue
            for k in range(i + 1, n):
                ck = self.chains[k]
                if (
                    k in dead
                    or ck.get("envoy")
                    or ck["cooldown"] > 0
                    or ck["age"] < COLLIDE_MIN_AGE_S
                ):
                    continue
                r = (
                    (self.blob_size * ci["thick_mult"])
                    + (self.blob_size * ck["thick_mult"])
                ) * 0.5 + 1.5
                dx = heads[k][0] - heads[i][0]
                dy = heads[k][1] - heads[i][1]
                if dx * dx + dy * dy > r * r:
                    continue
                angle = abs(_wrap_pi(ci["theta"] - ck["theta"]))
                if angle > math.pi / 2:
                    # head-on: both explode into a firework
                    mid = (
                        (heads[i][0] + heads[k][0]) / 2,
                        (heads[i][1] + heads[k][1]) / 2,
                    )
                    self._boom(mid, cols[i], cols[k])
                    dead.add(i)
                    dead.add(k)
                    break
                # glancing: elastic bounce (equal masses swap the
                # components along the collision axis)
                d = math.sqrt(dx * dx + dy * dy) or 1.0
                nx, ny = dx / d, dy / d
                va = (math.cos(ci["theta"]), math.sin(ci["theta"]))
                vb = (math.cos(ck["theta"]), math.sin(ck["theta"]))
                pa = va[0] * nx + va[1] * ny
                pb = vb[0] * nx + vb[1] * ny
                va2 = (va[0] + (pb - pa) * nx, va[1] + (pb - pa) * ny)
                vb2 = (vb[0] + (pa - pb) * nx, vb[1] + (pa - pb) * ny)
                ci["theta"] = self._clamp_heading(
                    math.atan2(va2[1], va2[0])
                )
                ck["theta"] = self._clamp_heading(
                    math.atan2(vb2[1], vb2[0])
                )
                ci["p0"] = heads[i]
                ck["p0"] = heads[k]
                ci["cooldown"] = COLLIDE_COOLDOWN_S
                ck["cooldown"] = COLLIDE_COOLDOWN_S
        if dead:
            keep = [idx for idx in range(n) if idx not in dead]
            self.chains = [self.chains[idx] for idx in keep]
            cols = cols[keep]
        return cols

    # ── sparks ─────────────────────────────────────────────────────────

    def _update_sparks(self, dt):
        n = self.s_n
        if n <= 0:
            return
        self.s_life[:n] -= dt
        alive = self.s_life[:n] > 0.0
        k = int(np.count_nonzero(alive))
        for arr in (
            self.s_x,
            self.s_y,
            self.s_vx,
            self.s_vy,
            self.s_life,
        ):
            arr[:k] = arr[:n][alive]
        self.s_rgb[:k] = self.s_rgb[:n][alive]
        self.s_n = k
        if k:
            drag = math.exp(-SPARK_DRAG * dt)
            self.s_vx[:k] *= drag
            self.s_vy[:k] *= drag
            self.s_x[:k] += self.s_vx[:k] * dt
            self.s_y[:k] += self.s_vy[:k] * dt

    def _splat_sparks(self, buf):
        n = self.s_n
        if n <= 0:
            return
        size = 2.1
        keep = self.k_dist <= size
        k_dx = self.k_dx[keep]
        k_dy = self.k_dy[keep]
        k_w = (1.0 - self.k_dist[keep] / (size + 0.5)).astype(np.float32)
        xi = np.round(self.s_x[:n]).astype(np.int32)
        yi = np.round(self.s_y[:n]).astype(np.int32)
        px = (xi[:, None] + k_dx[None, :]).ravel()
        py = (yi[:, None] + k_dy[None, :]).ravel()
        valid = (
            (px >= 0)
            & (px < self.r_width)
            & (py >= 0)
            & (py < self.r_height)
        )
        if not valid.any():
            return
        idx = (py * self.r_width + px)[valid]
        fade = np.clip(self.s_life[:n] / SPARK_LIFE_S, 0.0, 1.0)
        w = (
            np.broadcast_to(k_w[None, :], (n, k_w.size)).ravel()[valid]
        )
        for ch in range(3):
            col = (
                np.broadcast_to(
                    (self.s_rgb[:n, ch] * fade)[:, None], (n, k_w.size)
                ).ravel()[valid]
            )
            buf[..., ch] += np.bincount(
                idx, weights=w * col, minlength=self._n_cells
            ).reshape(self.r_height, self.r_width)

    # ── particle handoff (family interop) ──────────────────────────────

    def _handoff_snapshot(self):
        if getattr(self, "r_width", None) is None:
            return None
        heads = [self._head_pos(c) for c in self.chains]
        n = len(heads)
        return {
            "src": "squiggles",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": np.array([p[0] for p in heads], dtype=np.float32),
            "py": np.array([p[1] for p in heads], dtype=np.float32),
            "grad": np.array(
                [c["grad"] for c in self.chains], dtype=np.float32
            ),
            "bright": np.array(
                [c["bright"] for c in self.chains], dtype=np.float32
            ),
            "gradient": self._config.get("gradient"),
            "spin_sign": 0.0,
            "blob_size": float(self.blob_size),
            "flow": "in",
            "center_px": (float(self.cx), float(self.cy)),
            "trail": None,
            "n": n,
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
        virtual = self._virtual
        live = snap is not None
        if snap is None:
            sibling = (
                getattr(virtual, "_transition_effect", None)
                if virtual
                else None
            )
            if sibling is not None and sibling is not self and hasattr(
                sibling, "_handoff_snapshot"
            ):
                try:
                    snap = sibling._handoff_snapshot()
                    live = True
                except Exception:
                    snap = None
            if snap is None and virtual is not None:
                snap = particle_handoff.take(
                    getattr(virtual, "id", "") or ""
                )
        if not snap or tuple(snap["dims"]) != (self.r_width, self.r_height):
            return
        if snap["src"] == "radial":
            # radial implodes over phase 1 — hold, then burst one chain
            # per radial segment out of its center at the bloom point
            frac = particle_handoff.transition_progress(virtual)
            if (
                live
                and allow_hold
                and frac is not None
                and frac < particle_handoff.BLOOM_START
            ):
                self._radial_hold = {
                    "snap": snap,
                    "t0": particle_handoff.now(),
                }
            else:
                self._radial_burst(snap)
            return
        if snap["src"] in ("pacman", "dancer") and live and allow_hold:
            # pacman fades its maze (dancer: somersaults out) over phase 1 — hold
            # the adoption until the entities morph at PACMAN_MORPH_START
            frac = particle_handoff.transition_progress(virtual)
            if (
                frac is not None
                and frac < particle_handoff.PACMAN_MORPH_START
            ):
                self._pacman_hold = {
                    "snap": snap,
                    "t0": particle_handoff.now(),
                }
                return
        g = snap.get("gradient")
        if g and g != self._config.get("gradient"):
            self._apply_config({"gradient": g}, validate=False, fire_event=False)
        rng = self._rng
        k = min(len(snap["px"]), self.max_chains)
        order = np.argsort(snap["bright"])[::-1][:k]
        for i in order:
            pos = (float(snap["px"][i]), float(snap["py"][i]))
            jitter = math.radians(float(rng.uniform(-30.0, 30.0)))
            theta = math.atan2(self.cy - pos[1], self.cx - pos[0])
            if math.hypot(pos[0] - self.cx, pos[1] - self.cy) < 4.0:
                theta = float(rng.uniform(0.0, 2 * math.pi))
            c = self._new_chain(
                pos,
                theta + jitter,
                grad=float(snap["grad"][i]),
                bright=float(np.clip(snap["bright"][i], 0.4, 1.0)),
            )
            for _ in range(2 * max(1, self.step_size)):
                self._walk_one(c)
            self._trim(c, self.step_count)
            self.chains.append(c)

    def _radial_burst(self, snap):
        """Radial→squiggles payoff: the imploded radial bursts into one
        chain per radial edge/segment, flying outward from its center."""
        g = snap.get("gradient")
        if g and g != self._config.get("gradient"):
            self._apply_config(
                {"gradient": g}, validate=False, fire_event=False
            )
        virtual = self._virtual
        sib = (
            getattr(virtual, "_transition_effect", None) if virtual else None
        )
        k = 0
        try:
            if sib is not None and getattr(sib, "NAME", None) == "Radial":
                k = int(sib._config.get("edges") or 0)
        except Exception:
            k = 0
        if k <= 0:
            k = int(snap.get("edges") or 6)
        k = max(2, min(k, self.max_chains))
        c_px = snap.get("center_px") or (self.cx, self.cy)
        rng = self._rng
        base = float(rng.uniform(0.0, 2 * math.pi))
        for i in range(k):
            theta = base + (2 * math.pi * i) / k
            c = self._new_chain((float(c_px[0]), float(c_px[1])), theta)
            c["grad"] = float(i / max(k - 1, 1))
            self._walk_one(c)
            self.chains.append(c)

    # ── squiggles → radial envoys ──────────────────────────────────────

    def _edge_point_towards(self, target, desired_theta):
        """Edge-pool point whose direction TO `target` best matches
        `desired_theta`."""
        best, best_err = None, None
        for (c, r) in self._edge_pool:
            d = math.atan2(target[1] - r, target[0] - c)
            e = abs(_wrap_pi(d - desired_theta))
            if best_err is None or e < best_err:
                best, best_err = (c, r), e
        return best or self._edge_pool[0]

    def _launch_envoys(self, inc):
        """Two chains enter from opposite sides aimed at the incoming
        radial's center; they collide there exactly at the bloom point
        and the radial erupts out of the explosion."""
        w, h = self.r_width, self.r_height
        tx = (w - 1) * float(inc._config.get("x_offset", 0.5))
        ty = (h - 1) * float(inc._config.get("y_offset", 0.5))
        rng = self._rng
        pair = []
        for want in (
            math.pi / 2 + math.radians(float(rng.uniform(-20, 20))),
            -math.pi / 2 + math.radians(float(rng.uniform(-20, 20))),
        ):
            pos = self._edge_point_towards((tx, ty), want)
            theta = math.atan2(ty - pos[1], tx - pos[0])
            c = self._new_chain(pos, theta)
            c["envoy"] = True
            c["target"] = (tx, ty)
            for _ in range(START_SEGS * max(1, self.step_size)):
                self._walk_one(c)
            self._trim(c, self.step_count)
            self.chains.append(c)
            pair.append(c)
        self._envoys = {"chains": pair, "target": (tx, ty)}

    def _drive_envoys(self, virtual, cols):
        """Retime the envoys every frame so they meet at the target when
        the crossfade hits BLOOM_START, then explode them together."""
        env = self._envoys
        if env is None:
            return cols
        alive = [c for c in env["chains"] if c in self.chains]
        p = particle_handoff.transition_progress(virtual)
        if not alive:
            self._envoys = None
            return cols
        tx, ty = env["target"]
        total_s = None
        if p is not None:
            frames = float(getattr(virtual, "transition_frame_total", 0) or 0)
            rate = float(getattr(virtual, "refresh_rate", 60) or 60)
            if frames > 0 and rate > 0:
                total_s = frames / rate
        done = p is None or p >= particle_handoff.BLOOM_START
        for c in alive:
            hx, hy = self._head_pos(c)
            dist = math.hypot(tx - hx, ty - hy)
            if dist < 2.0:
                done = True
            if total_s is not None and p is not None and not done:
                remain_s = max(
                    (particle_handoff.BLOOM_START - p) * total_s, 0.05
                )
                c["speed_override"] = min(max(dist / remain_s, 4.0), 90.0)
        if done:
            idxs = [self.chains.index(c) for c in alive]
            a = cols[idxs[0]] if idxs[0] < len(cols) else (255.0, 220.0, 60.0)
            b = cols[idxs[-1]] if idxs[-1] < len(cols) else a
            self._boom((tx, ty), a, b)
            self._boom((tx, ty), b, a)
            keep = [
                i for i in range(len(self.chains)) if i not in set(idxs)
            ]
            self.chains = [self.chains[i] for i in keep]
            cols = cols[keep]
            self._envoys = None
        return cols

    # ── charge/lull/drop choreography ──────────────────────────────────
    # SpotFX writes `phase` (instant) and ramps `phase_progress` 0→1 over
    # the event's ramp. charge: chains bounce off the silhouette instead of
    # exiting while spawning ramps up; lull: old-TV switch-off — the frame
    # squashes vertically to a line, then the line pinches to a held dot;
    # drop: a fan of chains erupts from the center on the phase's first
    # frame, and everything returns to normal (`phase` self-resets to
    # "none") once the post-burst settle finishes.

    def _enter_phase(self, phase):
        self._phase = phase
        self._phase_t = 0.0
        self._phase_rate = 0.0
        self._phase_done_t = None
        if phase == "drop":
            self._drop = {"burst_t": None}
        if phase in ("drop", "none"):
            # back to normal population no matter how we got here
            self.max_chains = int(self._config["max_blobs"])

    def _phase_step(self, dt):
        pend = self._phase_pending
        if pend is not None:
            self._phase_pending = None
            if pend != self._phase:
                self._enter_phase(pend)
        if self._phase == "none":
            return
        self._phase_t += dt
        # orphan watchdog: a charge/lull whose payoff never arrives
        # releases itself — walls open, the CRT snaps back on, no burst
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self.phase_progress, self._phase_t,
            self._phase_done_t,
        )
        if due:
            _LOGGER.info(
                "squiggles: %s watchdog release after %.1fs",
                self._phase, self._phase_t,
            )
            self._phase = "none"
            self._drop = None
            self.max_chains = int(self._config["max_blobs"])
            self._phase_rate = 0.0
            self._apply_config(
                {"phase": "none", "phase_progress": 0.0},
                validate=False,
                fire_event=False,
            )
            return
        if self._phase == "charge":
            p = float(np.clip(self.phase_progress, 0.0, 1.0))
            base_max = int(self._config["max_blobs"])
            self.max_chains = int(min(
                CHAIN_HARD_CAP,
                round(base_max * (1.0 + CHARGE_MAX_X * p)),
            ))
            self._phase_rate = CHARGE_RATE * p
        elif self._phase == "drop":
            drop = self._drop
            if drop is None:
                drop = self._drop = {"burst_t": None}
            if drop["burst_t"] is None:
                # DROP ANCHORS ITS START TO THE MARK (his ruling,
                # 2026-08-20, data/drops-still-fire-early-star-does-not-
                # explode/ — Black Hole was tried as a "known-good" drop
                # reference and then withdrawn when he found it early too).
                # This REPLACES the progress-gated end-anchor
                # (`p >= 0.995`, DROP_FALLBACK_S) PR fm/spectra-squiggles-
                # drop-timing-and-a-much-bigger-explosion built to mirror
                # Black Hole's THEN-confirmed-good timing — that anchor is
                # now superseded, not merely unused: the burst fires on the
                # phase's first frame instead, matching orbits.py's own
                # drop branch. His other two asks from that same PR (burst
                # count, burst speed/lingering) are untouched — this only
                # moves WHEN the burst fires, not its size or pace.
                drop["burst_t"] = 0.0
                self._phase_burst()
            else:
                drop["burst_t"] += dt
                if drop["burst_t"] >= DROP_SETTLE_S:
                    self._phase = "none"
                    self._drop = None
                    self.max_chains = int(self._config["max_blobs"])
                    # sanctioned in-render config path (under the effect
                    # lock); self-reset so an identical later drop write
                    # edges again
                    self._apply_config(
                        {"phase": "none", "phase_progress": 0.0},
                        validate=False,
                        fire_event=False,
                    )

    def _bounce(self, c):
        """Charge/lull wall bounce: a chain that reaches the silhouette
        turns back toward the interior instead of exiting."""
        hx, hy = self._head_pos(c)
        jitter = math.radians(float(self._rng.uniform(-35.0, 35.0)))
        c["theta"] = self._clamp_heading(
            math.atan2(self.cy - hy, self.cx - hx) + jitter
        )
        c["slot"] = self._closest_slot(c["theta"])
        c["seg_left"] = 0
        c["p0"] = (hx, hy)
        c["cooldown"] = max(c["cooldown"], 0.2)
        for _ in range(2):
            self._walk_one(c)

    def _phase_burst(self):
        """Drop payoff: a fan of chains erupts from the center (bypasses
        max_chains — the explosion must always land). Pinned to
        DROP_BURST_SPEED_MULT of normal travel speed (fixed, not
        audio-scaled) so the fan lingers outward instead of flashing
        straight past — never cleared, so it holds for the chain's whole
        flight to the silhouette edge."""
        rng = self._rng
        k = int(min(DROP_BURST_N, CHAIN_HARD_CAP - len(self.chains)))
        if k <= 0:
            return
        base = float(rng.uniform(0.0, 2 * math.pi))
        burst_speed = self.base_speed * DROP_BURST_SPEED_MULT
        for i in range(k):
            theta = (
                base
                + (2 * math.pi * i) / k
                + math.radians(float(rng.uniform(-10.0, 10.0)))
            )
            c = self._new_chain((self.cx, self.cy), theta)
            c["speed_override"] = burst_speed
            for _ in range(2):
                self._walk_one(c)
            self.chains.append(c)

    def _phase_crt(self, buf):
        """Lull post-process: CRT switch-off. Vertical squash to a bright
        line over the first CRT_SPLIT of the lull, then the line pinches
        horizontally into a held white dot at the center."""
        if self._phase != "lull":
            return buf
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        # progress-driven once it moves (hand-scrubbable in the LedFX UI);
        # the wall-clock fallback only runs while progress sits at 0
        f = p if p > 0.0 else min(self._phase_t / LULL_CRT_S, 1.0)
        if f <= 0.0:
            return buf
        h, w = buf.shape[:2]
        cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
        if f < CRT_SPLIT:
            s = f / CRT_SPLIT
            fy = 1.0 - 0.96 * (s * s * (3.0 - 2.0 * s))
            fx = 1.0
            dot = 0.0
        else:
            s = (f - CRT_SPLIT) / (1.0 - CRT_SPLIT)
            fy = 0.04
            fx = 1.0 - 0.96 * (s * s * (3.0 - 2.0 * s))
            dot = min(1.0, 0.3 + s)
        # squeezing the picture concentrates its energy — brighten with it
        boost = 1.0 + 2.2 * (1.0 - fy) + 1.5 * (1.0 - fx)
        ys = np.arange(h)
        xs = np.arange(w)
        sy = cy + (ys - cy) / max(fy, 1e-3)
        sx = cx + (xs - cx) / max(fx, 1e-3)
        vy = (sy >= 0) & (sy <= h - 1)
        vx = (sx >= 0) & (sx <= w - 1)
        out = np.zeros_like(buf)
        if vy.any() and vx.any():
            yi = np.round(sy[vy]).astype(np.int32)
            xi = np.round(sx[vx]).astype(np.int32)
            out[np.ix_(vy, vx)] = buf[yi[:, None], xi[None, :]] * boost
        if dot > 0.0:
            # the lingering phosphor dot — the held "prepped" state
            out[int(round(cy)), int(round(cx))] = np.maximum(
                out[int(round(cy)), int(round(cx))], 235.0 * dot
            )
        return np.minimum(out, 255.0)

    # ── frame ──────────────────────────────────────────────────────────

    def draw(self):
        if self.test:
            self.draw_test(self.m_draw)
            return
        if self._handoff_pending:
            self._handoff_pending = False
            self._adopt_handoff()
        virtual = self._virtual
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
        if self._radial_hold is not None:
            hold = self._radial_hold
            frac = particle_handoff.transition_progress(virtual)
            if getattr(virtual, "_transition_effect", None) is self:
                self._radial_hold = None  # switched away mid-hold
            elif (
                frac is None
                or frac >= particle_handoff.BLOOM_START
                or particle_handoff.now() - hold["t0"]
                > particle_handoff.ERUPT_HOLD_MAX_S
            ):
                self._radial_hold = None
                self._radial_burst(hold["snap"])
        if self._envoys is None:
            inc = particle_handoff.incoming_sibling(virtual, self)
            if inc is not None and getattr(inc, "NAME", None) == "Radial":
                self._launch_envoys(inc)
        dt = self.passed
        if not np.isfinite(dt) or dt <= 0.0:
            dt = 1.0 / 60.0
        dt = min(dt, DT_MAX)

        self._phase_step(dt)

        speed_px = self.base_speed * (1.0 + self.speed_audio * self.impulse)
        steps_target = self._steps_target()

        # spawn pacing (blackhole model); the lull owns a dark screen, the
        # charge adds a steady progress-driven influx on top
        if self._phase != "lull":
            self.spawn_acc += (
                self.spawn_rate * (1.0 + self.spawn_audio * self.impulse)
                + self._phase_rate
            ) * dt
            n_new = int(self.spawn_acc)
            self.spawn_acc -= n_new
            if self._beat_pending:
                self._beat_pending = False
                n_new += self.beat_burst
            if n_new:
                self._spawn(n_new)
        else:
            self._beat_pending = False

        for c in self.chains:
            self._advance_chain(
                c, dt, c.get("speed_override") or speed_px, steps_target
            )
        if self._phase in ("charge", "lull"):
            # walls are solid while the room charges: chains that reach the
            # silhouette turn back inward instead of exiting
            for c in self.chains:
                head = c["path"][-1]
                if not self._inside(head[0], head[1]):
                    self._bounce(c)
        else:
            self.chains = [c for c in self.chains if not self._offscreen(c)]

        # colors: one gradient sample per chain
        if self.chains:
            grads = np.array(
                [c["grad"] for c in self.chains], dtype=np.float32
            )
            cols = self.get_gradient_color_vectorized1d(grads).astype(
                np.float32
            )
        else:
            cols = np.zeros((0, 3), dtype=np.float32)

        cols = self._collide(cols)
        cols = self._drive_envoys(virtual, cols)
        self._update_sparks(dt)

        # paint chains pixel-exact on the device lattice: every lit pixel
        # is a real LED; the tail tapers like a comet
        w, h = self.r_width, self.r_height
        buf = np.zeros((h, w, 3), dtype=np.float32)
        bright_gain = min(
            1.0, 0.55 + self.brightness_audio * self.impulse * 0.6
        )
        for i, c in enumerate(self.chains):
            if i >= len(cols):
                break
            fade = min(c["age"] / FADE_IN_S, 1.0)
            col = cols[i] * (bright_gain * fade * c["bright"])
            n = len(c["path"])
            cs = np.fromiter((p[0] for p in c["path"]), dtype=np.int32,
                             count=n)
            rs = np.fromiter((p[1] for p in c["path"]), dtype=np.int32,
                             count=n)
            taper = np.linspace(0.35, 1.0, n, dtype=np.float32)
            t = int(min(6, max(1, round(self.blob_size * c["thick_mult"]))))
            offs = self.lat.thick_offsets(t)
            cc = (cs[:, None] + offs[None, :, 0]).ravel()
            rr = (rs[:, None] + offs[None, :, 1]).ravel()
            ww = np.broadcast_to(
                taper[:, None], (n, len(offs))
            ).ravel()
            m = (cc >= 0) & (cc < w) & (rr >= 0) & (rr < h)
            if m.any():
                buf[rr[m], cc[m]] = np.maximum(
                    buf[rr[m], cc[m]], ww[m, None] * col[None, :]
                )

        self._splat_sparks(buf)
        buf = self._phase_crt(buf)
        self.matrix = Image.fromarray(
            np.clip(buf, 0.0, 255.0).astype(np.uint8), "RGB"
        )
