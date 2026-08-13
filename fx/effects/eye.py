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

DT_MAX = 0.1
N_FLAME = 24        # flame tongues around the iris rim (few, distinct)
GAZE_N = 8          # ring positions (index 0 is the center "primary")
TARGET_TIMEOUT_S = 4.0   # give up searching and pick a new target
SNAP_LAND_S = 0.08  # a snap dart covers the remaining distance this fast
# eyeball-rotation illusion: gaze offset → rotation angle. A gaze at 0.5
# (the default ring) reads as ~40° of eyeball turn.
GAZE_ANGLE_GAIN = 1.4   # radians of eyeball turn per unit of gaze offset
GAZE_ANGLE_MAX = 0.9    # ~52° cap
PUPIL_LEAD = 0.5        # pupil leads into the gaze by this × sin(θ) × iris_r
# transitions (see particle_handoff): the eye donates a ring of rim
# particles on the way out ("the iris explodes into blobs") and pulls a
# predecessor's particles onto its rim on the way in ("blobs fall in and
# form the iris").
N_RIM = 28          # rim particles in the outgoing snapshot
INFALL_S = 1.1      # seconds adopted particles take to reach the rim
INFALL_CAP = 160    # max adopted particles animated
FORM_S = 0.35       # iris scale-in after a radial implode
BLINK_OPEN_S = 0.4  # lid-reveal opening time (dancer transitions)
# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; see _phase_step)
CHARGE_IRIS_GROW = 0.30    # iris radius gain at full charge
CHARGE_PUPIL_SHRINK = 0.5  # pupil radius loss at full charge
CHARGE_RELAX_S = 0.5       # ease charged sizes back after the payoff
LULL_FALLBACK_S = 2.0      # lull closes on this timer if no progress ramp
DROP_OPEN_S = 0.18         # lid snaps open this fast on the drop
DROP_BURST_S = 0.45        # flame-explosion envelope decay constant
DROP_TOTAL_S = 1.2         # drop phase self-resets to "none" after this
LID_PAUSE_START = 0.50     # progress where the lid pauses on the iris
LID_PAUSE_END = 0.75       # progress where the final close begins


class Eye2d(Twod, GradientEffect):
    NAME = "Eye"
    CATEGORY = "Matrix"
    # spin supersedes gradient_roll; color_blend stays hidden — colors update
    # in place, recreation would reset the gaze. phase/phase_progress are
    # SpotFX-driven choreography; advanced (not hidden) so the arc can be
    # hand-scrubbed in the LedFX UI for tuning.
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + ["gradient_roll", "color_blend"]
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "impulse_decay",
        "phase",
        "phase_progress",
    ]

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "gradient",
                description="Iris + flame color gradient",
                default="linear-gradient(90deg, #ff0000 0.00%,#ff7800 14.00%,#ffc800 28.00%,#00ff00 42.00%,#00c78c 56.00%,#0000ff 70.00%,#800080 84.00%,#ff00b2 98.00%)",
            ): validate_gradient,
            vol.Optional(
                "iris_size",
                description="Iris radius as a fraction of the panel",
                default=0.54,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=0.8)),
            vol.Optional(
                "pupil_size",
                description="Pupil radius as a fraction of the panel",
                default=0.36,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.03, max=0.6)),
            vol.Optional(
                "spin",
                description="Iris rotation speed (rev/s); sign sets direction, music speeds it up",
                default=0.08,
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                "flames",
                description="Flame amount from the iris rim; 0 = no flames",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "flame_audio",
                description="How much music boosts flame intensity and randomness",
                default=2.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "drift_speed",
                description="Base gaze search speed",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=2.0)),
            vol.Optional(
                "gaze_radius",
                description="Radius of the 8-position gaze ring",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=0.6)),
            vol.Optional(
                "gaze_depth",
                description="3D eyeball illusion: the iris foreshortens and the pupil leads as the eye looks away from center; 0 = flat googly eye",
                default=0.6,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "snap_threshold",
                description="Audio impulse a beat needs to snap the gaze to a new position",
                default=0.6,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "snap_hold",
                description="Base seconds the gaze holds after a snap (bigger hits hold longer)",
                default=0.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "speed_audio",
                description="How much the selected band boosts the gaze search speed",
                default=2.9,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
            vol.Optional(
                "spin_audio",
                description="How much the selected band speeds up the iris spin; 0 = constant spin",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
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
                "frequency_range",
                description="Audio band driving the eye",
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
        }
    )

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        # Gaze + flame state lives here (NOT do_once) so it survives config
        # patches — do_once re-runs on every config change and a mid-song
        # reset would teleport the eye and re-roll every flame tongue.
        self._rng = np.random.default_rng()
        self.gaze = np.zeros(2, dtype=np.float32)   # normalized, eye-space
        self._target_idx = 0
        self._target_t = 0.0
        self._hold_left = 0.0
        self._beat_pending = False
        self._beat_kick = 0.0
        self._rush = 0.0       # snap-dart speed burst (fluid, not a teleport)
        self._arc_sign = 1.0   # which way the current search leg curves
        self._wander_t = 0.0
        self._wander_seed = float(self._rng.uniform(0, 2 * np.pi))
        self._reach_jig = 1.0  # breathing reach boundary (mean-reverts to 1)
        self.impulse = 0.0
        self.spin_total = 0.0
        self._flow_t = 0.0
        self._burst = 0.0
        self._lid = 0.0        # 0 = open, 1 = fully closed
        self._drop_slam = False  # drop caught the lids mid-close
        self._charge_amt = 0.0
        # per-tongue flicker oscillators + jitter accumulator (slow, lazy
        # licks — music adds the chaos)
        self.fl_speed = self._rng.uniform(0.3, 1.0, N_FLAME).astype(np.float32)
        self.fl_phase = self._rng.uniform(0, 2 * np.pi, N_FLAME).astype(np.float32)
        self.fl_speed2 = self._rng.uniform(0.8, 1.8, N_FLAME).astype(np.float32)
        self.fl_phase2 = self._rng.uniform(0, 2 * np.pi, N_FLAME).astype(np.float32)
        self.fl_jit = np.zeros(N_FLAME, dtype=np.float32)
        self._t = 0.0
        self._fl_t = 0.0   # flame clock — runs faster as the flames grow
        # transition state
        self._handoff_pending = True
        self._infall = None      # predecessor particles flying to the rim
        self._form = None        # iris scale-in progress (radial explode-in)
        self._erupt_hold = None  # waiting for a collapsing radial's pinch
        self._pacman_hold = None  # waiting for pacman's maze to fade
        self._blink_in = None    # entering from dancer: lids start closed
        self._pull = None        # outgoing to radial: gaze pulled to center
        # small dot kernel for infall particles
        span = np.arange(-2, 3)
        kdx, kdy = np.meshgrid(span, span)
        kd = np.sqrt(kdx**2 + kdy**2).ravel()
        keep = kd <= 2.0
        self.dk_dx = kdx.ravel()[keep].astype(np.int32)
        self.dk_dy = kdy.ravel()[keep].astype(np.int32)
        self.dk_w = (1.0 - kd[keep] / 2.6).astype(np.float32)

    def config_updated(self, config):
        super().config_updated(config)
        self.iris_size = self._config["iris_size"]
        self.pupil_size = self._config["pupil_size"]
        self.spin = self._config["spin"]
        self.flames = self._config["flames"]
        self.flame_audio = self._config["flame_audio"]
        self.drift_speed = self._config["drift_speed"]
        self.gaze_radius = self._config["gaze_radius"]
        self.snap_threshold = self._config["snap_threshold"]
        self.snap_hold = self._config["snap_hold"]
        self.gaze_depth = self._config["gaze_depth"]
        self.speed_audio = self._config["speed_audio"]
        self.spin_audio = self._config["spin_audio"]
        self.x_offset = self._config["x_offset"]
        self.y_offset = self._config["y_offset"]

        # position list: index 0 = center, 1..8 spread on the gaze ring
        ang = np.arange(GAZE_N) * (2 * np.pi / GAZE_N)
        self.positions = np.zeros((GAZE_N + 1, 2), dtype=np.float32)
        self.positions[1:, 0] = self.gaze_radius * np.cos(ang)
        self.positions[1:, 1] = self.gaze_radius * np.sin(ang)

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
            self._drop = None
        else:
            # non-creation pass: a changed phase key arms the edge
            self._phase_pending = new_phase if new_phase != self._phase else None

        self.power_func = self.POWER_FUNCS_MAPPING[
            self._config["frequency_range"]
        ]
        self.impulse_filter = self.create_filter(
            alpha_decay=self._config["impulse_decay"], alpha_rise=0.99
        )

    def audio_data_updated(self, data):
        impulse = self.impulse_filter.update(getattr(data, self.power_func)())
        self.impulse = float(impulse) if np.isfinite(impulse) else 0.0
        if data.bpm_beat_now():
            self._beat_pending = True

    def do_once(self):
        super().do_once()
        self.cx = (self.r_width - 1) * self.x_offset
        self.cy = (self.r_height - 1) * self.y_offset
        # Gaze positions stretch to the panel ellipse; the eye itself stays
        # circular via the min-axis scale.
        self.sx = max((self.r_width - 1) / 2.0, 1e-6)
        self.sy = max((self.r_height - 1) / 2.0, 1e-6)
        self.s_min = max(min(self.sx, self.sy), 1.0)
        y_idx, x_idx = np.indices((self.r_height, self.r_width))
        self.px_x = x_idx.astype(np.float32)
        self.px_y = y_idx.astype(np.float32)

    # ── transitions (particle handoff) ──────────────────────────────────
    # Outgoing: a ring of rim particles ("the iris explodes into blobs") —
    # orbits glides them into tethers and flies the surplus outward,
    # fireworks explodes each one, squiggles grows chains, blackhole lets
    # them fall in, dancer assembles from them at the lid reveal. The
    # native block carries gaze/spin state across same-type recreations
    # (flare fallback POSTs recreate the instance — the gaze must not
    # visibly reset to center).

    def _handoff_snapshot(self):
        if getattr(self, "r_width", None) is None:
            return None
        eye_px = self.cx + float(self.gaze[0]) * self.sx
        eye_py = self.cy + float(self.gaze[1]) * self.sy
        iris_px = self.iris_size * self.s_min
        a = (np.arange(N_RIM, dtype=np.float32) / N_RIM) * 2 * np.pi
        return {
            "src": "eye",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": (eye_px + np.cos(a) * iris_px).astype(np.float32),
            "py": (eye_py + np.sin(a) * iris_px).astype(np.float32),
            "grad": ((a / (2 * np.pi) + self.spin_total) % 1.0).astype(
                np.float32
            ),
            "bright": np.ones(N_RIM, dtype=np.float32),
            "gradient": self._config.get("gradient"),
            "spin_sign": float(np.sign(self.spin)) or 1.0,
            "blob_size": 2.0,
            "flow": "out",
            "center_px": (float(eye_px), float(eye_py)),
            "captured": np.zeros(N_RIM, dtype=bool),
            "trail": None,
            "native": {
                "gaze": self.gaze.copy(),
                "target_idx": self._target_idx,
                "spin_total": self.spin_total,
                "hold_left": self._hold_left,
                "lid": self._lid,
                # a flare recreation mid-lull/charge must CONTINUE the
                # phase — otherwise the stale-phase guard kills the close
                # and the still-running progress tween re-edges it late
                "phase": self._phase,
                "phase_t": self._phase_t,
                "phase_progress": self.phase_progress,
                "charge_amt": self._charge_amt,
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
        """First-draw adoption: read the live crossfade sibling if present,
        else the registry. A pre-fetched `snap` (the pacman-hold release
        path) skips the fetch."""
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
        if snap["src"] == "eye":
            # same-type recreation: continue exactly where we were
            native = snap.get("native") or {}
            g = native.get("gaze")
            if g is not None and len(g) == 2:
                self.gaze = np.asarray(g, dtype=np.float32).copy()
            self._target_idx = int(native.get("target_idx", self._target_idx))
            self.spin_total = float(native.get("spin_total", self.spin_total))
            self._hold_left = float(native.get("hold_left", 0.0))
            self._lid = float(native.get("lid", 0.0))
            self._charge_amt = float(native.get("charge_amt", 0.0))
            # resume a mid-flight charge/lull (a drop doesn't carry — its
            # burst state died with the predecessor; safer to re-edge)
            ph = native.get("phase", "none")
            if ph in ("charge", "lull"):
                self._phase = ph
                self._phase_t = float(native.get("phase_t", 0.0))
                self.phase_progress = float(
                    native.get("phase_progress", self.phase_progress)
                )
                # keep a DIFFERENT pending edge (e.g. a drop written
                # between creation and first draw); only drop a pending
                # re-edge of the phase we just resumed
                if self._phase_pending == ph:
                    self._phase_pending = None
            return
        # cross-type: carry the predecessor's gradient + rotation sign so
        # colors and spin are continuous at the switch instant — SpotFX
        # repaints on its next color action and stays the source of truth.
        patch = {}
        g = snap.get("gradient")
        if g and g != self._config.get("gradient"):
            patch["gradient"] = g
        spin_sign = float(snap.get("spin_sign") or 0.0)
        if spin_sign and self.spin and np.sign(self.spin) != spin_sign:
            patch["spin"] = abs(self._config["spin"]) * spin_sign
        if patch:
            # sanctioned in-render config path (we're under the effect lock)
            self._apply_config(patch, validate=False, fire_event=False)
        if snap["src"] == "dancer" and live:
            # blink-in: lids start closed, open at the bloom point to
            # reveal the eye
            self._lid = 1.0
            self._blink_in = {"t0": particle_handoff.now(), "open": False}
            return
        if snap["src"] == "pacman" and live and allow_hold:
            # pacman fades its maze over phase 1 — hold the adoption until
            # the entities morph at PACMAN_MORPH_START
            frac = particle_handoff.transition_progress(virtual)
            if frac is not None and frac < particle_handoff.PACMAN_MORPH_START:
                self._pacman_hold = {
                    "snap": snap, "t0": particle_handoff.now(),
                }
                return
        if snap["src"] == "radial":
            # the collapsing radial owns phase 1; the eye then explodes
            # back out of the pinch — flame burst + iris scale-in
            if live and particle_handoff.transition_progress(virtual) is not None:
                self._erupt_hold = {"t0": particle_handoff.now()}
            else:
                self._burst = 1.0
                self._form = 0.0
            return
        # generic particle predecessor: its blobs fall in and form the iris
        px = snap.get("px")
        py = snap.get("py")
        if px is None or len(px) == 0:
            return
        k = int(min(len(px), INFALL_CAP))
        idx = np.linspace(0, len(px) - 1, k).astype(np.int64)
        sx_ = ((np.asarray(px)[idx] - self.cx) / self.s_min).astype(np.float32)
        sy_ = ((np.asarray(py)[idx] - self.cy) / self.s_min).astype(np.float32)
        ex = float(self.gaze[0]) * self.sx / self.s_min
        ey = float(self.gaze[1]) * self.sy / self.s_min
        grad = snap.get("grad")
        if grad is not None and len(grad) == len(px):
            grad = np.asarray(grad)[idx].astype(np.float32)
        else:
            grad = self._rng.random(k).astype(np.float32)
        bright = snap.get("bright")
        if bright is not None and len(bright) == len(px):
            bright = np.clip(np.asarray(bright)[idx], 0.3, 1.0).astype(
                np.float32
            )
        else:
            bright = np.ones(k, dtype=np.float32)
        self._infall = {
            "t": 0.0,
            "sx": sx_,
            "sy": sy_,
            "ang": np.arctan2(sy_ - ey, sx_ - ex).astype(np.float32),
            "grad": grad,
            "bright": bright,
            "dur": (self._rng.uniform(0.75, 1.15, k) * INFALL_S).astype(
                np.float32
            ),
        }

    # ── charge/lull/drop choreography ───────────────────────────────────
    # SpotFX writes `phase` (instant) and ramps `phase_progress` 0→1 over
    # the event's ramp. charge: flames reverse inward while the iris grows
    # and the pupil shrinks; lull: the gaze returns to center and an
    # emoji-style lid closes (fast start → pause just overlapping the iris
    # → full close); drop: the lid snaps open with a flame explosion, then
    # `phase` self-resets to "none" (so an identical later write edges).

    def _enter_phase(self, phase):
        self._phase = phase
        self._phase_t = 0.0
        self._phase_done_t = None
        if phase == "drop":
            self._drop = {"t": 0.0, "fired": False}
            # a short lull can leave the lids mid-close when the drop
            # lands — slam them shut first (fast blink), THEN explode open
            self._drop_slam = 0.03 < self._lid < 0.97
        else:
            self._drop = None
            self._drop_slam = False

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
        # releases itself as a silent drop (open, no explosion)
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self.phase_progress, self._phase_t,
            self._phase_done_t,
        )
        if due:
            _LOGGER.info(
                "eye: %s watchdog release after %.1fs",
                self._phase, self._phase_t,
            )
            self._phase = "drop"
            self._phase_t = 0.0
            self.phase_progress = 0.0
            self._drop = {"t": 0.0, "fired": True, "silent": True}
            self._drop_slam = False  # gentle exit: just open
            return
        if self._phase == "charge":
            self._charge_amt = float(np.clip(self.phase_progress, 0.0, 1.0))
        elif self._phase == "drop":
            drop = self._drop
            if drop is None:
                drop = self._drop = {"t": 0.0, "fired": False}
            if not drop["fired"] and not self._drop_slam:
                # (the slam holds the burst until the lids have snapped
                # shut — the explosion then rides the opening)
                drop["fired"] = True
                self._burst = 1.0
                # explosion randomness spike
                self.fl_jit += self._rng.uniform(
                    0.3, 1.2, N_FLAME
                ).astype(np.float32)
            drop["t"] += dt
            if drop["t"] >= DROP_TOTAL_S:
                self._phase = "none"
                self._drop = None
                self._apply_config(
                    {"phase": "none", "phase_progress": 0.0},
                    validate=False,
                    fire_event=False,
                )

    def _lid_travel(self, p, y_from, y_to, y_overlap):
        """Lid travel fraction for lull progress `p`: fast ease-out to just
        overlapping the iris edge, a near-still pause, then the close. Works
        for both directions — the ratio is signed the same way for a lid
        coming down (y_from < y_to) or up (y_from > y_to)."""
        span = y_to - y_from
        if abs(span) < 1e-6:
            return 1.0
        f1 = float(np.clip((y_overlap - y_from) / span, 0.0, 0.9))
        if p <= LID_PAUSE_START:
            q = p / LID_PAUSE_START
            return f1 * (1.0 - (1.0 - q) ** 2.2)
        if p <= LID_PAUSE_END:
            q = (p - LID_PAUSE_START) / (LID_PAUSE_END - LID_PAUSE_START)
            return f1 + 0.02 * q
        # complete a touch BEFORE the ramp end (0.93) so end-of-ramp jitter
        # (a drop landing a hair early) can't strand a slit-open lid
        q = min((p - LID_PAUSE_END) / (0.93 - LID_PAUSE_END), 1.0)
        return (f1 + 0.02) + (1.0 - f1 - 0.02) * q * q

    def _update_gaze(self, dt, beat):
        imp = self.impulse
        energy = min(self.speed_audio * imp, 1.5)
        self._beat_kick *= float(np.exp(-dt / 0.35))
        self._rush *= float(np.exp(-dt / 0.15))
        # breathing reach boundary: a mean-reverting jiggle, so the eye
        # sometimes homes right in on a target and sometimes gives up early
        self._reach_jig += (1.0 - self._reach_jig) * min(dt * 0.8, 1.0)
        self._reach_jig += float(self._rng.normal(0.0, 0.55)) * float(
            np.sqrt(dt)
        )
        self._reach_jig = float(np.clip(self._reach_jig, 0.45, 1.5))
        in_lull = self._phase == "lull"

        arc = 0.0
        if beat:
            if (
                not in_lull
                and self._pull is None
                and imp >= self.snap_threshold
                and self._lid < 0.5
            ):
                # big hit: dart to a random ring position (never the center)
                # — still fluid motion, just very fast (see _rush below)
                choices = [
                    i for i in range(1, GAZE_N + 1) if i != self._target_idx
                ]
                self._target_idx = int(self._rng.choice(choices))
                self._hold_left = self.snap_hold * (0.4 + 1.2 * min(imp, 1.0))
                self._rush = 1.0
                self._arc_sign = 1.0 if self._rng.random() < 0.5 else -1.0
                self._target_t = 0.0
            else:
                self._beat_kick = 1.0

        if in_lull or self._pull is not None:
            # look at the primary position (lull) or the incoming radial's
            # center (gather), quickly
            target = self.positions[0] if in_lull else self._pull
            v = self.drift_speed * 3.0
        elif self._hold_left > 0.0:
            # the stare: finish the dart at rush speed first, then hold
            target = self.positions[self._target_idx]
            dist = float(np.hypot(*(target - self.gaze)))
            if dist <= 0.03:
                self._hold_left -= dt
                return
            v = max(
                self.drift_speed * (1.0 + 8.0 * self._rush),
                dist / SNAP_LAND_S,
            )
        else:
            target = self.positions[self._target_idx]
            self._target_t += dt
            # energetic music searches faster AND gets closer before moving on
            reach = (
                max(0.02, 0.30 * (1.0 - min(energy, 1.0))) * self._reach_jig
            )
            dist = float(np.hypot(*(target - self.gaze)))
            if dist <= reach or self._target_t > TARGET_TIMEOUT_S:
                choices = [
                    i for i in range(1, GAZE_N + 1) if i != self._target_idx
                ]
                self._target_idx = int(self._rng.choice(choices))
                self._target_t = 0.0
                self._arc_sign = 1.0 if self._rng.random() < 0.5 else -1.0
                target = self.positions[self._target_idx]
            v = (
                self.drift_speed
                * (0.25 + 0.75 * energy)
                * (1.0 + 0.9 * self._beat_kick)
            )
            # slow music swings in orbit-like arcs; hot bursts dart straight
            arc = (1.0 - min(energy, 1.0)) * 0.9

        delta = target - self.gaze
        dist = float(np.hypot(*delta))
        step = v * dt
        if dist > 1e-6:
            dhat = delta / dist
            perp = 0.0
            if arc > 0.0:
                # curved pursuit: a per-leg arc plus a slower meander so the
                # path drifts around the direct line while searching
                self._wander_t += dt * (0.8 + 1.5 * energy)
                perp = self._arc_sign * arc * (
                    0.55 + 0.45 * float(np.sin(self._wander_t * 0.6))
                ) + 0.4 * float(
                    np.sin(self._wander_t * 2.1 + self._wander_seed)
                ) * (1.0 - 0.6 * min(energy, 1.0))
            if step >= dist and abs(perp) < 0.2:
                self.gaze = target.copy()
            else:
                phat = np.array([-dhat[1], dhat[0]], dtype=np.float32)
                move = dhat + perp * phat
                move /= float(np.hypot(*move))
                self.gaze = (
                    self.gaze + move.astype(np.float32)
                    * min(step, dist * 1.5)
                )
        # micro-saccade jitter keeps the eye alive between moves
        self.gaze = self.gaze + self._rng.normal(
            0.0, 0.004 + 0.008 * min(imp, 1.0), 2
        ).astype(np.float32) * np.sqrt(dt)

    def draw(self):
        if self.test:
            self.draw_test(self.m_draw)
            return

        dt = min(self.passed, DT_MAX)
        if not np.isfinite(dt) or dt <= 0:
            dt = 1.0 / 60.0
        self._t += dt
        imp = self.impulse

        if self._handoff_pending:
            self._handoff_pending = False
            self._adopt_handoff()

        virtual = self._virtual
        # held explode-in: a collapsing radial predecessor owns phase 1
        if self._erupt_hold is not None:
            hold = self._erupt_hold
            frac = particle_handoff.transition_progress(virtual)
            if getattr(virtual, "_transition_effect", None) is self:
                self._erupt_hold = None  # switched away mid-hold
            elif (
                frac is None
                or frac >= particle_handoff.BLOOM_START
                or particle_handoff.now() - hold["t0"]
                > particle_handoff.ERUPT_HOLD_MAX_S
            ):
                self._erupt_hold = None
                self._burst = 1.0
                self._form = 0.0
        # held pacman adoption: its maze fades over phase 1 — adopt at the
        # morph point, re-reading the live sibling
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

        # outgoing choreography, chosen by who is coming in
        inc = particle_handoff.incoming_sibling(virtual, self)
        inc_name = getattr(inc, "NAME", None) if inc is not None else None
        self._pull = None
        blink_out = None
        if inc_name == "Radial":
            # gather: look at the radial's center so its bloom explodes
            # straight out of the iris
            rx = float(inc._config.get("x_offset", 0.5))
            ry = float(inc._config.get("y_offset", 0.5))
            self._pull = np.array([
                ((self.r_width - 1) * rx - self.cx) / max(self.sx, 1e-6),
                ((self.r_height - 1) * ry - self.cy) / max(self.sy, 1e-6),
            ], dtype=np.float32)
        elif inc_name == "Dancer":
            # blink reveal: close over phase 1, reopen on the incoming
            # dancer at the bloom point
            blink_out = particle_handoff.transition_progress(virtual)

        self._phase_step(dt)
        beat = self._beat_pending
        self._beat_pending = False
        self._update_gaze(dt, beat)

        # charged sizes ease back once the phase is over
        if self._phase not in ("charge", "lull"):
            self._charge_amt = max(0.0, self._charge_amt - dt / CHARGE_RELAX_S)
        charge = self._charge_amt
        # iris scale-in after a radial pinch (the "explode back out")
        size_gain = 1.0
        if self._form is not None:
            self._form += dt / FORM_S
            if self._form >= 1.0:
                self._form = None
            else:
                f = self._form
                size_gain = 0.2 + 0.8 * f * (2.0 - f)
        iris_r = self.iris_size * (1.0 + CHARGE_IRIS_GROW * charge) * size_gain
        pupil_r = min(
            self.pupil_size * (1.0 - CHARGE_PUPIL_SHRINK * charge) * size_gain,
            iris_r * 0.85,
        )
        # the iris fades in as a predecessor's blobs arrive on the rim
        body_gain = 1.0
        if self._infall is not None:
            body_gain = 0.25 + 0.75 * min(self._infall["t"] / INFALL_S, 1.0)
        # blink-out phase 2: the eye is "gone behind the lids" — only the
        # opening lids render while the dancer fades in underneath
        body_show = not (
            blink_out is not None
            and blink_out >= particle_handoff.BLOOM_START
        )

        # iris spin: spin_audio (independent of the gaze's speed_audio)
        # speeds it up with music; 0 = constant spin
        spin_v = self.spin * (1.0 + self.spin_audio * imp)
        self.spin_total = (self.spin_total + spin_v * dt) % 1.0
        # flame radial flow, deliberately lazy (reverses inward while
        # charging); music adds only a gentle push
        self._flow_t += dt * (0.3 + 0.5 * imp)
        self._burst = self._burst * float(np.exp(-dt / DROP_BURST_S))
        if self._burst < 0.01:
            self._burst = 0.0

        # ── geometry ────────────────────────────────────────────────────
        eye_px = self.cx + float(self.gaze[0]) * self.sx
        eye_py = self.cy + float(self.gaze[1]) * self.sy
        dxp = (self.px_x - eye_px) / self.s_min
        dyp = (self.px_y - eye_py) / self.s_min

        # eyeball rotation (gaze_depth): the gaze offset maps to a turn
        # angle; the iris (and its flames) foreshorten along the gaze
        # direction and the pupil leads into it — the painted cues that
        # make the eye read as physically looking AT a spot instead of a
        # flat disc sliding around.
        g_mag = float(np.hypot(*self.gaze))
        depth = self.gaze_depth
        if depth > 0.001 and g_mag > 1e-4:
            ux = float(self.gaze[0]) / g_mag
            uy = float(self.gaze[1]) / g_mag
            theta = min(g_mag * GAZE_ANGLE_GAIN, GAZE_ANGLE_MAX)
            cos_eff = 1.0 - depth * (1.0 - float(np.cos(theta)))
            lead = depth * PUPIL_LEAD * float(np.sin(theta))
        else:
            ux, uy = 1.0, 0.0
            cos_eff, lead = 1.0, 0.0

        if cos_eff < 0.999:
            # squash the along-gaze axis: circle math in stretched space
            # renders as an ellipse with its minor axis along the gaze
            p_alo = (dxp * ux + dyp * uy) / cos_eff
            p_per = -dxp * uy + dyp * ux
            tx = p_alo * ux - p_per * uy
            ty = p_alo * uy + p_per * ux
        else:
            tx, ty = dxp, dyp
        dist = np.sqrt(tx * tx + ty * ty)
        ang = np.arctan2(ty, tx)
        a_norm = (ang * (1.0 / (2 * np.pi)) + self.spin_total) % 1.0
        aa = 1.5 / self.s_min  # ~1.5px soft edge

        out = np.asarray(self.matrix, dtype=np.float32)

        # ── infall: predecessor particles falling onto the iris rim ─────
        if self._infall is not None and body_show:
            inf = self._infall
            inf["t"] += dt
            e = np.clip(inf["t"] / inf["dur"], 0.0, 1.0)
            if float(e.min()) >= 1.0:
                self._infall = None
            else:
                es = e * e * (3.0 - 2.0 * e)
                ex = float(self.gaze[0]) * self.sx / self.s_min
                ey = float(self.gaze[1]) * self.sy / self.s_min
                fx = inf["sx"] + (
                    ex + np.cos(inf["ang"]) * iris_r - inf["sx"]
                ) * es
                fy = inf["sy"] + (
                    ey + np.sin(inf["ang"]) * iris_r - inf["sy"]
                ) * es
                fade = inf["bright"] * np.clip((1.0 - e) / 0.15, 0.0, 1.0)
                alive = fade > 0.01
                if alive.any():
                    xi = np.round(
                        self.cx + fx[alive] * self.s_min
                    ).astype(np.int32)
                    yi = np.round(
                        self.cy + fy[alive] * self.s_min
                    ).astype(np.int32)
                    rgb = self.get_gradient_color_vectorized1d(
                        inf["grad"][alive]
                    ).astype(np.float32) * fade[alive][:, None]
                    n_dot, n_k = xi.size, self.dk_dx.size
                    pxs = (xi[:, None] + self.dk_dx[None, :]).ravel()
                    pys = (yi[:, None] + self.dk_dy[None, :]).ravel()
                    valid = (
                        (pxs >= 0) & (pxs < self.r_width)
                        & (pys >= 0) & (pys < self.r_height)
                    )
                    idxf = (pys * self.r_width + pxs)[valid]
                    kw = np.broadcast_to(
                        self.dk_w[None, :], (n_dot, n_k)
                    ).ravel()[valid]
                    cells = self.r_width * self.r_height
                    for ch in range(3):
                        vals = np.broadcast_to(
                            rgb[:, ch][:, None], (n_dot, n_k)
                        ).ravel()[valid] * kw
                        out[..., ch] += np.bincount(
                            idxf, weights=vals, minlength=cells
                        ).reshape(self.r_height, self.r_width)

        # ── flames ──────────────────────────────────────────────────────
        amp = self.flames * (1.0 + 1.5 * self.flame_audio * imp)
        if charge > 0.05:
            amp = max(amp, (0.35 + 0.65 * charge) * max(self.flames, 0.35))
        amp_gate = amp + 3.2 * self._burst
        if body_show and amp_gate > 0.01:
            # per-tongue flicker: two detuned oscillators + a jitter random
            # walk whose feed grows with music intensity
            jd = float(np.exp(-dt / 0.18))
            feed = 0.04 + 0.5 * min(self.flame_audio * imp, 1.5)
            if beat:
                self.fl_jit += self._rng.uniform(
                    0.0, 0.8, N_FLAME
                ).astype(np.float32) * min(imp + 0.2, 1.2)
            self.fl_jit = (
                self.fl_jit * jd
                + self._rng.normal(0.0, feed, N_FLAME).astype(np.float32)
                * np.sqrt(dt) * 2.0
            )
            # flicker speed grows with flame size: small idle flames lick
            # lazily, big ones (music, charge, the drop burst) rage
            self._fl_t += dt * (0.4 + 1.2 * min(amp_gate, 2.5))
            flick = 0.55 + 0.45 * np.sin(
                self._fl_t * self.fl_speed + self.fl_phase
            )
            flick *= 0.75 + 0.25 * np.sin(
                self._fl_t * self.fl_speed2 + self.fl_phase2
            )
            flick = np.clip(flick + self.fl_jit, 0.08, 2.2)
            # the explosion (drop / reveal) squirts sideways: burst
            # amplitude is weighted toward the axis perpendicular to the
            # lid motion (horizontal), per tongue in SCREEN space
            if self._burst > 0.0:
                bin_ang = (
                    (np.arange(N_FLAME, dtype=np.float32) + 0.5) / N_FLAME
                    - self.spin_total
                ) * (2 * np.pi)
                w_h = (0.25 + 0.75 * np.cos(bin_ang) ** 2).astype(np.float32)
                amp_bins = amp + 4.5 * self._burst * w_h
            else:
                amp_bins = amp
            length = iris_r * (0.20 + 1.0 * amp_bins) * flick
            length *= 1.0 + 1.6 * charge
            length = np.clip(length, 0.02, 3.0).astype(np.float32)

            # flames rotate with the iris: bin by spun angle, lerp between
            # neighbouring tongues for smooth edges
            fpos = a_norm * N_FLAME
            f0 = np.floor(fpos).astype(np.int32) % N_FLAME
            f1 = (f0 + 1) % N_FLAME
            fw = (fpos - np.floor(fpos)).astype(np.float32)
            flen = length[f0] * (1.0 - fw) + length[f1] * fw

            d = dist - iris_r
            rel = d / np.maximum(flen, 1e-4)
            fmask = (d >= 0.0) & (rel < 1.0)
            if fmask.any():
                reli = rel[fmask]
                inten = (1.0 - reli) ** 1.6
                # radial shimmer flowing outward (inward while charging).
                # It fades IN away from the rim so the flame base sits flush
                # against the iris edge — the flames are an extension of the
                # iris, not a fringe with a seam.
                fdir = -1.0 if charge > 0.05 else 1.0
                shim = 0.72 + 0.28 * np.sin(
                    d[fmask] * 14.0 - fdir * self._flow_t * 10.0
                )
                w = np.clip(reli / 0.25, 0.0, 1.0)
                inten *= (1.0 - w) + w * shim
                frgb = self.get_gradient_color_vectorized1d(
                    a_norm[fmask]
                ).astype(np.float32)
                out[fmask] += frgb * (inten[:, None] * body_gain)

        # ── iris ────────────────────────────────────────────────────────
        # Opaque out to the rim, antialiasing ramp OUTWARD (over the flame
        # base, which shares the gradient color) — an inward ramp blends the
        # rim against the black background and reads as a dark ring between
        # iris and flames.
        alpha_i = np.clip((iris_r + aa - dist) / aa, 0.0, 1.0)
        imask = alpha_i > 0.0
        if body_show and imask.any():
            irgb = self.get_gradient_color_vectorized1d(
                a_norm[imask]
            ).astype(np.float32)
            t_rad = np.clip(
                (dist[imask] - pupil_r) / max(iris_r - pupil_r, 1e-4),
                0.0, 1.0,
            )
            # brighter toward the rim, full brightness at the edge — the
            # flames continue seamlessly from here (no limbal ring)
            shade = 0.55 + 0.45 * t_rad
            a = alpha_i[imask][:, None] * body_gain
            out[imask] = out[imask] * (1.0 - a) + irgb * shade[:, None] * a

        # ── pupil (black) ───────────────────────────────────────────────
        # leads into the gaze direction (same squashed frame as the iris)
        if body_show:
            if lead > 0.0:
                lpx = lead * iris_r * ux
                lpy = lead * iris_r * uy
                pa = ((dxp - lpx) * ux + (dyp - lpy) * uy) / cos_eff
                pp = -(dxp - lpx) * uy + (dyp - lpy) * ux
                dist_p = np.sqrt(pa * pa + pp * pp)
            else:
                dist_p = dist
            alpha_p = np.clip((pupil_r - dist_p) / aa, 0.0, 1.0)
            pmask = alpha_p > 0.0
            if pmask.any():
                out[pmask] *= (1.0 - alpha_p[pmask] * body_gain)[:, None]

        # ── eyelids ─────────────────────────────────────────────────────
        if self._phase == "lull":
            p = max(
                self.phase_progress,
                min(self._phase_t / LULL_FALLBACK_S, 1.0),
            )
            self._lid = float(np.clip(p, 0.0, 1.0))
        elif self._phase == "drop":
            if self._drop_slam:
                # finish the interrupted close FAST, then explode open
                self._lid = min(1.0, self._lid + dt / 0.06)
                if self._lid >= 1.0:
                    self._drop_slam = False
            else:
                self._lid = max(0.0, self._lid - dt / DROP_OPEN_S)
        elif blink_out is not None:
            # outgoing to dancer: close over phase 1, reopen after the
            # bloom point — the incoming dancer is revealed underneath
            if blink_out < particle_handoff.BLOOM_START:
                self._lid = min(
                    blink_out / particle_handoff.BLOOM_START, 1.0
                )
            else:
                self._lid = max(
                    0.0,
                    1.0 - (blink_out - particle_handoff.BLOOM_START) / 0.25,
                )
        elif self._blink_in is not None:
            # entering from dancer: hold closed, then open to reveal the eye
            hold = self._blink_in
            if not hold["open"]:
                self._lid = 1.0
                frac = particle_handoff.transition_progress(virtual)
                if (
                    frac is None
                    or frac >= particle_handoff.BLOOM_START
                    or particle_handoff.now() - hold["t0"]
                    > particle_handoff.ERUPT_HOLD_MAX_S
                ):
                    hold["open"] = True
            else:
                self._lid = max(0.0, self._lid - dt / BLINK_OPEN_S)
                if self._lid <= 0.0:
                    self._blink_in = None
        else:
            self._lid = max(0.0, self._lid - dt / 0.25)

        if self._lid > 0.001:
            top_ny = (0.0 - eye_py) / self.s_min
            bot_ny = (float(self.r_height - 1) - eye_py) / self.s_min
            sag = 0.30 * iris_r
            # both lids close together: the upper sweeps down, the lower
            # sweeps up, each pausing just past its iris edge, meeting at a
            # line slightly below the eye center
            y_meet = 0.15 * iris_r
            y_open = top_ny - sag - 0.05
            y_lo_start = bot_ny + sag + 0.05
            lw = 2.0 / self.s_min
            f_up = self._lid_travel(
                self._lid, y_open, y_meet, -0.8 * iris_r)
            f_lo = self._lid_travel(
                self._lid, y_lo_start, y_meet + lw, 0.8 * iris_r)
            y_up = y_open + (y_meet - y_open) * f_up
            y_lo = y_lo_start + (y_meet + lw - y_lo_start) * f_lo

            u = dxp / (self.sx / self.s_min)
            curve = sag * (1.0 - np.clip(u * u, 0.0, 1.0))
            up_edge = y_up + curve
            lo_edge = y_lo + curve
            # the lids are just thick lines — colored 180° from the gradient
            # center (position 0.0 on the wheel, not spun with the iris) —
            # over the plain background; no special lid surface
            lid_rgb = self.get_gradient_color_vectorized1d(
                np.zeros(1, dtype=np.float32)
            ).astype(np.float32)[0]
            bg = getattr(self, "_bg_color", np.zeros(3)).astype(np.float32)
            covered = (dyp <= up_edge) | (dyp >= lo_edge)
            out[covered] = bg
            lw_half = max(1.8 / self.s_min, 0.06 * iris_r)
            for edge in (up_edge, lo_edge):
                line = np.clip(
                    1.0 - np.abs(dyp - edge) / lw_half, 0.0, 1.0
                )
                lmask = line > 0.0
                if lmask.any():
                    out[lmask] += line[lmask][:, None] * lid_rgb

        self.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB"
        )
