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

CAP = 48            # particle buffer cap (count max + departing extras)
SUBSTEPS = 3        # path sub-samples per frame (gap-free smear)
DT_MAX = 0.1
KERNEL_R = 8        # max blob radius the offset table supports
# fly-in / adoption glide duration is the `enter_time` config param
LEAVE_FADE_S = 1.2  # fade-out horizon for departing particles
LEAVE_SPEED = 1.4   # departure speed, radii per second
HANDOFF_ENTER_S = 0.65  # fast fly-in for handoff spawns — long enough that
                        # the shoot-out from the center reads clearly
HANDOFF_LEAVE_S = 0.55  # fast exit for surplus particles after a handoff
SLOT_EASE_S = 0.6   # tether re-spacing ease time constant
SPIKE_COOL_S = 0.12  # min gap between jog kicks
ENTRY_R = 1.35      # normalized radius where new particles appear
# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; see _phase_step)
CHARGE_PEAK_N = 10   # population grows to this, then sheds to 1
CHARGE_PEAK_AT = 0.45  # progress fraction where the shed begins
LULL_FALL_S = 3.0    # fall-to-center fallback when no lull ramp arrives
DROP_FLY_S = 0.4     # seconds the payoff blobs take to fly back out
DROP_SETTLE_S = 4.2  # drop boost decay / phase auto-reset horizon — raised
                      # in tandem with DROP_EJECTA_SPEED (see below) so the
                      # slower ejecta aren't cut off by the fade timer before
                      # they clear the panel
DROP_BOOST = 2.5     # extra orbit speed at the drop instant
# The drop explodes 3× the configured population from the center; the
# surplus two thirds are ballistic ejecta that fly fully off-panel before
# the boost window ends — only one third settles into orbits.
DROP_EJECTA_X = 2        # ejecta per kept blob (3× total spawn)
# radii/s — tuned so the ejecta's own panel-clearing flight (not this fade
# horizon) averages ~3.0s at his real scene's fallback particle_count=3,
# his ask (data/spectra-orbits-blob-persistence/HIS-DECISION.md), up from
# the ~1.4-1.6s the previous (0.9, 1.6) speed produced
DROP_EJECTA_SPEED = (0.49, 0.87)

# Every per-particle SoA array, in one place so compaction and the particle
# handoff native snapshot can never drift out of sync with each other.
_SOA_NAMES = (
    "p_mode", "p_slot", "p_slot_frac", "p_phase", "p_ro", "p_jog",
    "p_enter", "p_ex", "p_ey", "p_lvx", "p_lvy", "p_leave",
    "p_nf1", "p_nf2", "p_np1", "p_np2", "p_wf", "p_wp", "p_gf", "p_gp",
    "p_grad", "p_x0", "p_y0", "p_scatter", "p_bright", "p_grad_from",
    "p_erate", "p_lfade",
)


class Orbits2d(Twod, GradientEffect):
    """A fixed population of particles, each tethered to a point on a ring
    around the center. Particles orbit their tethers; the tether ring itself
    spins. Jiggle trades clean orbits for smooth per-particle wander and
    decorrelates each particle's audio response. Physics is circular in
    normalized space and projected to a panel-filling ellipse, like Blackhole.
    """

    NAME = "Orbits"
    CATEGORY = "Matrix"
    # gradient_spin supersedes gradient_roll for this effect; color_blend
    # stays hidden — colors update in place, recreation kills the particles.
    # phase/phase_progress are SpotFX-driven choreography; advanced (not
    # hidden) so the arc can be hand-scrubbed in the LedFX UI for tuning.
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + ["gradient_roll", "color_blend"]
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "impulse_decay",
        "color_shift",
        "phase",
        "phase_progress",
    ]

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "gradient",
                description="Particle colors, sampled evenly across the gradient",
                default="linear-gradient(90deg, #ff0000 0.00%,#ff7800 14.00%,#ffc800 28.00%,#00ff00 42.00%,#00c78c 56.00%,#0000ff 70.00%,#800080 84.00%,#ff00b2 98.00%)",
            ): validate_gradient,
            vol.Optional(
                "particle_count",
                description="Number of particles kept alive on the matrix",
                default=6,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
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
                description="Tether ring radius; 0 tethers every particle to the center",
                default=0.4,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.8)),
            vol.Optional(
                "tether_scatter",
                description="Tether spacing bias: 0 = perfectly equidistant, 1 = fully random placement",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "enter_time",
                description="Seconds a new or adopted particle takes to glide into its orbit",
                default=2.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=5.0)),
            vol.Optional(
                "orbit_radius",
                description="Radius of each particle's path around its tether",
                default=0.25,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.02, max=0.8)),
            vol.Optional(
                "blob_size",
                description="Particle radius in pixels",
                default=1.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=6.0)),
            vol.Optional(
                "spin",
                description="Tether ring rotation speed (fraction of base speed)",
                default=0.15,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "base_speed",
                description="Base orbit speed in revolutions per second",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=2.0)),
            vol.Optional(
                "reverse",
                description="Reverse the spin direction (orbits and ring)",
                default=False,
            ): bool,
            vol.Optional(
                "jiggle",
                description="0 = clean synced orbits, 1 = independent smooth wander within the orbit radius",
                default=0.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "reactivity_scale",
                description="Master scale multiplying every audio reactivity below",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "speed_jump",
                description="Max speed boost the music can add to a particle",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "speed_jog",
                description="How hard spikes/beats knock particles off course",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "brightness_audio",
                description="How much the music pumps particle brightness",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "size_audio",
                description="How much the music inflates particle size",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "trail_decay",
                description="Comet-trail length: 0 = crisp dots, 1 = long smear",
                default=0.4,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "gradient_spin",
                description="Roll particle colors along the gradient over time (rev/s)",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                "color_shift",
                description="Rotate the particle→color assignment by this many slots (nudge +1 to make colors jump A,B,C → C,A,B)",
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
        self.p_mode = np.zeros(CAP, dtype=np.int8)  # 0 active 1 entering 2 leaving
        self.p_slot = np.zeros(CAP, dtype=np.int16)
        self.p_slot_frac = np.zeros(CAP, dtype=np.float32)  # ring position 0..1
        self.p_phase = np.zeros(CAP, dtype=np.float32)      # orbit angle
        self.p_ro = np.zeros(CAP, dtype=np.float32)         # radial jog offset
        self.p_jog = np.zeros(CAP, dtype=np.float32)        # angular kick rad/s
        self.p_enter = np.zeros(CAP, dtype=np.float32)      # fly-in progress
        self.p_ex = np.zeros(CAP, dtype=np.float32)         # fly-in start point
        self.p_ey = np.zeros(CAP, dtype=np.float32)
        self.p_lvx = np.zeros(CAP, dtype=np.float32)        # departure velocity
        self.p_lvy = np.zeros(CAP, dtype=np.float32)
        self.p_leave = np.zeros(CAP, dtype=np.float32)      # departure age
        # smooth-noise oscillators: radius (2 bands), omega, reactivity gain
        self.p_nf1 = np.zeros(CAP, dtype=np.float32)
        self.p_nf2 = np.zeros(CAP, dtype=np.float32)
        self.p_np1 = np.zeros(CAP, dtype=np.float32)
        self.p_np2 = np.zeros(CAP, dtype=np.float32)
        self.p_wf = np.zeros(CAP, dtype=np.float32)
        self.p_wp = np.zeros(CAP, dtype=np.float32)
        self.p_gf = np.zeros(CAP, dtype=np.float32)
        self.p_gp = np.zeros(CAP, dtype=np.float32)
        self.p_grad = np.zeros(CAP, dtype=np.float32)
        self.p_x0 = np.zeros(CAP, dtype=np.float32)  # last normalized position
        self.p_y0 = np.zeros(CAP, dtype=np.float32)
        # per-particle random ring position used when tether_scatter > 0
        self.p_scatter = np.zeros(CAP, dtype=np.float32)
        # last drawn brightness (exported in the particle handoff)
        self.p_bright = np.zeros(CAP, dtype=np.float32)
        # carried-over gradient position an entering particle blends FROM
        # (NaN = no carry-over)
        self.p_grad_from = np.full(CAP, np.nan, dtype=np.float32)
        # fly-in speed multiplier (>1 = handoff quick-spawn)
        self.p_erate = np.ones(CAP, dtype=np.float32)
        # per-particle departure fade duration
        self.p_lfade = np.full(CAP, LEAVE_FADE_S, dtype=np.float32)
        self._soa = tuple(getattr(self, name) for name in _SOA_NAMES)
        self.n = 0
        self._booted = False
        # adopt a predecessor's on-screen particles on the first draw
        self._handoff_pending = True
        # predecessor blob size we ease FROM after a handoff (+ its age)
        self._size_from = None
        self._size_age = None
        # outgoing-to-radial collapse state; None = normal physics
        self._collapse = None
        # held center eruption while a radial predecessor collapses
        self._erupt_hold = None
        # held pacman adoption while its maze fades out (phase 1)
        self._pacman_hold = None
        self.t = 0.0
        self.ring_phase = 0.0
        self.roll_total = 0.0
        self.impulse = 0.0
        self.slow = 0.0
        self._beat_pending = False
        self._spike_cool = 0.0
        self._rng = np.random.default_rng()
        self.trail = None

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

        self.power_func = self.POWER_FUNCS_MAPPING[
            self._config["frequency_range"]
        ]
        decay = self._config["impulse_decay"]
        self.impulse_filter = self.create_filter(
            alpha_decay=decay, alpha_rise=0.99
        )
        # slow reference for spike (onset) detection
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
            self._charge_n0 = 1
            self._pos_scale = 1.0
            self._lull_f = 0.0
            self._omega_scale = 1.0
            self._phase_done_t = None
        else:
            # non-creation pass: a changed phase key arms the edge
            self._phase_pending = new_phase if new_phase != self._phase else None

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
        # Physics is circular in normalized space; this projection stretches
        # it into a panel-filling ellipse.
        self.sx = self.radius_scale * (self.r_width - 1) / 2.0
        self.sy = self.radius_scale * (self.r_height - 1) / 2.0
        if self.trail is None or self.trail.shape[:2] != (
            self.r_height,
            self.r_width,
        ):
            self.trail = np.zeros(
                (self.r_height, self.r_width, 3), dtype=np.float32
            )

    def _compact(self, alive):
        count = int(np.count_nonzero(alive))
        for arr in self._soa:
            arr[:count] = arr[: self.n][alive]
        self.n = count

    def _spawn_entering(self, count, active=False):
        """Spawn `count` particles. Entering ones fly in from off-panel;
        `active` ones (initial population / effect restart) appear directly
        in orbit so a config change never replays the whole intro."""
        count = min(count, CAP - self.n)
        if count <= 0:
            return
        s = slice(self.n, self.n + count)
        rng = self._rng
        ang = rng.uniform(0.0, 2 * np.pi, count)
        if active:
            self.p_mode[s] = 0
            self.p_enter[s] = 1.0
            # NaN marks "no previous position": the draw pass snaps p_x0/p_y0
            # to the first computed orbit position (no streak from origin).
            self.p_x0[s] = np.nan
            self.p_y0[s] = np.nan
        else:
            self.p_mode[s] = 1
            self.p_enter[s] = 0.0
            self.p_ex[s] = ENTRY_R * np.cos(ang)
            self.p_ey[s] = ENTRY_R * np.sin(ang)
            self.p_x0[s] = self.p_ex[s]
            self.p_y0[s] = self.p_ey[s]
        self.p_scatter[s] = rng.random(count, dtype=np.float32)
        self.p_bright[s] = 0.0
        self.p_grad_from[s] = np.nan
        self.p_erate[s] = 1.0
        self.p_lfade[s] = LEAVE_FADE_S
        self.p_phase[s] = rng.uniform(0.0, 2 * np.pi, count)
        self.p_ro[s] = 0.0
        self.p_jog[s] = 0.0
        self.p_leave[s] = 0.0
        # smooth-noise oscillator frequencies ~0.25..1.2 Hz, random phases
        for freq, phase in (
            (self.p_nf1, self.p_np1),
            (self.p_nf2, self.p_np2),
            (self.p_wf, self.p_wp),
            (self.p_gf, self.p_gp),
        ):
            freq[s] = rng.uniform(1.5, 7.5, count)
            phase[s] = rng.uniform(0.0, 2 * np.pi, count)
        self.n += count

    def _manage_population(self):
        """Spawn fly-ins / mark fly-outs so mode<2 population matches
        particle_count, then (re)assign evenly-spaced ring slots."""
        tracked = np.flatnonzero(self.p_mode[: self.n] < 2)
        want = self.particle_count
        have = tracked.size
        if have < want:
            # First population appears in place; later additions fly in.
            self._spawn_entering(want - have, active=not self._booted)
            tracked = np.flatnonzero(self.p_mode[: self.n] < 2)
        elif have > want:
            # a random particle flies off in a random direction
            doomed = self._rng.choice(tracked, size=have - want, replace=False)
            ang = self._rng.uniform(0.0, 2 * np.pi, doomed.size)
            self.p_mode[doomed] = 2
            self.p_lvx[doomed] = LEAVE_SPEED * np.cos(ang)
            self.p_lvy[doomed] = LEAVE_SPEED * np.sin(ang)
            self.p_leave[doomed] = 0.0
            tracked = np.flatnonzero(self.p_mode[: self.n] < 2)
        self._booted = True
        # stable-order slot assignment; the rest ease into freed spots
        self.p_slot[tracked] = np.arange(tracked.size, dtype=np.int16)
        # fresh spawns (flying in, or placed in-place with no position yet)
        # start at their final slot angle instead of easing from 0
        fresh = tracked[
            ((self.p_mode[tracked] == 1) & (self.p_enter[tracked] == 0.0))
            | ~np.isfinite(self.p_x0[tracked])
        ]
        if fresh.size:
            self.p_slot_frac[fresh] = (
                self.p_slot[fresh].astype(np.float32) / max(tracked.size, 1)
            )

    def _handoff_snapshot(self):
        """Live particle state in the neutral handoff format (see
        particle_handoff module). None before the first render."""
        if getattr(self, "r_width", None) is None or self.trail is None:
            return None
        n = self.n
        px = self.cx + self.p_x0[:n] * self.sx
        py = self.cy + self.p_y0[:n] * self.sy
        px = np.where(np.isfinite(px), px, self.cx)
        py = np.where(np.isfinite(py), py, self.cy)
        return {
            "src": "orbits",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": px.astype(np.float32),
            "py": py.astype(np.float32),
            "grad": self.p_grad[:n].copy(),
            "bright": self.p_bright[:n].copy(),
            "gradient": self._config.get("gradient"),
            # rotation sign + blob size so a successor can continue the
            # motion instead of restating its own
            "spin_sign": -1.0 if self.reverse else 1.0,
            "blob_size": float(self.blob_size),
            "trail": self.trail,
            "native": {
                "n": n,
                "t": self.t,
                "ring_phase": self.ring_phase,
                "roll_total": self.roll_total,
                "arrays": {
                    name: getattr(self, name)[:n].copy()
                    for name in _SOA_NAMES
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
        if snap["src"] == "orbits":
            native = snap["native"]
            k = min(native["n"], CAP)
            for name, arr in native["arrays"].items():
                if hasattr(self, name):
                    getattr(self, name)[:k] = arr[:k]
            self.n = k
            self.t = float(native.get("t", 0.0))
            self.ring_phase = float(native.get("ring_phase", 0.0))
            self.roll_total = float(native.get("roll_total", 0.0))
            self._booted = True
            return
        # cross-type: carry the predecessor's gradient so colors are
        # continuous at the switch instant — SpotFX repaints on its next
        # color action and stays the source of truth. Same deal for the
        # rotation sign: our spin continues the swirl direction the
        # blackhole already had.
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
        # blob size eases from the predecessor's to ours over enter_time
        size_from = snap.get("blob_size")
        if size_from and size_from != self.blob_size:
            self._size_from = float(size_from)
            self._size_age = 0.0
        # blackhole geometry in our normalized space: where it spawned
        # blobs, and which way its flow ran
        c_px = snap.get("center_px")
        if c_px:
            ncx = (float(c_px[0]) - self.cx) / max(self.sx, 1e-6)
            ncy = (float(c_px[1]) - self.cy) / max(self.sy, 1e-6)
        else:
            ncx = ncy = 0.0
        flow_out = snap.get("flow") == "out"
        if snap["src"] == "radial":
            # "suck in then erupt": the collapsing radial owns phase 1 —
            # hold our center burst until it has pinched out (or erupt
            # immediately on the no-transition path)
            self._booted = True
            if live and particle_handoff.transition_progress(virtual) is not None:
                self._erupt_hold = {
                    "ncx": ncx,
                    "ncy": ncy,
                    "t0": particle_handoff.now(),
                }
            else:
                self._spawn_center_burst(ncx, ncy, self.particle_count)
            return
        # from blackhole: adopt the brightest blobs as entering particles
        # that glide from their current position into tether orbits.
        # Horizon-captured blobs are excluded entirely — they fade out in
        # place via the merged trail instead of being flown around.
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
            self._spawn_entering(want)
            got = self.n - base
            if got > 0:
                idx = order[:got]
                s = slice(base, self.n)
                ex = (snap["px"][idx] - self.cx) / max(self.sx, 1e-6)
                ey = (snap["py"][idx] - self.cy) / max(self.sy, 1e-6)
                self.p_ex[s] = ex
                self.p_ey[s] = ey
                self.p_x0[s] = ex
                self.p_y0[s] = ey
                self.p_grad[s] = snap["grad"][idx]
                self.p_grad_from[s] = snap["grad"][idx]
                self.p_bright[s] = np.clip(snap["bright"][idx], 0.3, 1.0)
        # deficit: fewer inherited blobs than particle_count — spawn the
        # rest NOW as fast fly-ins from the blackhole's spawn zone (its
        # center for eruption flow; the default rim entry matches infall)
        deficit = self.particle_count - got
        if deficit > 0:
            if flow_out:
                self._spawn_center_burst(ncx, ncy, deficit)
            else:
                base = self.n
                self._spawn_entering(deficit)
                k = self.n - base
                if k > 0:
                    s = slice(base, self.n)
                    self.p_erate[s] = max(
                        1.0, self.enter_time / HANDOFF_ENTER_S
                    )
        # surplus: the brightest extra blobs fly out along the blackhole's
        # flow — outward and off-panel for eruption flow, or sucked into the
        # center (arriving exactly as their fade completes) for infall.
        # Capped: everything beyond the cap just fades via the merged trail
        # (sprite cost during the switch stays bounded).
        extra = min(
            order.size - want,
            particle_handoff.SURPLUS_FLYOUT_MAX,
            CAP - self.n,
        )
        if extra > 0:
            idx = order[want : want + extra]
            base = self.n
            self._spawn_entering(extra)
            k = self.n - base
            if k > 0:
                idx = idx[:k]
                s = slice(base, self.n)
                ex = (snap["px"][idx] - self.cx) / max(self.sx, 1e-6)
                ey = (snap["py"][idx] - self.cy) / max(self.sy, 1e-6)
                self.p_mode[s] = 2
                self.p_x0[s] = ex
                self.p_y0[s] = ey
                self.p_grad[s] = snap["grad"][idx]
                self.p_bright[s] = np.clip(snap["bright"][idx], 0.2, 1.0)
                self.p_lfade[s] = HANDOFF_LEAVE_S
                dx = ex - ncx
                dy = ey - ncy
                if flow_out:
                    dist = np.sqrt(dx * dx + dy * dy) + 1e-6
                    speed = LEAVE_SPEED * 1.6
                    self.p_lvx[s] = dx / dist * speed
                    self.p_lvy[s] = dy / dist * speed
                else:
                    self.p_lvx[s] = -dx / HANDOFF_LEAVE_S
                    self.p_lvy[s] = -dy / HANDOFF_LEAVE_S

    def _spawn_drop_ejecta(self, count):
        """Drop explosion surplus: ballistic blobs that erupt from the
        center and fly fully off-panel before the boost window ends. They
        ride the existing 'leaving' machinery (mode 2, constant velocity,
        off-panel retirement) and stay bright almost to the exit."""
        base = self.n
        self._spawn_entering(count)
        k = self.n - base
        if k <= 0:
            return
        s = slice(base, self.n)
        rng = self._rng
        ang = rng.uniform(0.0, 2 * np.pi, k)
        spd = rng.uniform(*DROP_EJECTA_SPEED, k).astype(np.float32)
        jr = rng.uniform(0.0, 0.06, k).astype(np.float32)
        self.p_mode[s] = 2
        self.p_x0[s] = jr * np.cos(ang)
        self.p_y0[s] = jr * np.sin(ang)
        self.p_lvx[s] = (np.cos(ang) * spd).astype(np.float32)
        self.p_lvy[s] = (np.sin(ang) * spd).astype(np.float32)
        self.p_leave[s] = 0.0
        # fade horizon ≈ the boost window: they hold brightness while
        # flying and are retired by the off-panel check on exit
        self.p_lfade[s] = DROP_SETTLE_S
        self.p_grad[s] = rng.random(k, dtype=np.float32)

    def _spawn_center_burst(self, ncx, ncy, count):
        """Fast fly-ins erupting from a predecessor's center point
        (normalized coords) — the blackhole eruption zone or a collapsed
        radial's center."""
        base = self.n
        self._spawn_entering(count)
        k = self.n - base
        if k <= 0:
            return
        s = slice(base, self.n)
        self.p_erate[s] = max(1.0, self.enter_time / HANDOFF_ENTER_S)
        ang = self._rng.uniform(0.0, 2 * np.pi, k)
        jr = self._rng.uniform(0.0, 0.08, k)
        self.p_ex[s] = ncx + jr * np.cos(ang)
        self.p_ey[s] = ncy + jr * np.sin(ang)
        self.p_x0[s] = self.p_ex[s]
        self.p_y0[s] = self.p_ey[s]

    # ── charge/lull/drop choreography ───────────────────────────────────
    # SpotFX writes `phase` (instant) and ramps `phase_progress` 0→1 over
    # the event's ramp. charge: the population swells to CHARGE_PEAK_N then
    # sheds down to a single blob as the ramp completes; lull: that blob
    # keeps orbiting while its whole orbit collapses to the center and it
    # shrinks; drop: it explodes back into the configured population as a
    # fast center burst, then `phase` self-resets to "none".

    def _enter_phase(self, phase):
        prev_scale = self._pos_scale
        self._phase = phase
        self._phase_t = 0.0
        self._phase_done_t = None
        if phase == "charge":
            tracked = int(np.count_nonzero(self.p_mode[: self.n] < 2))
            self._charge_n0 = max(tracked, 1)
            self._drop_state = None
        elif phase == "drop":
            self._drop_state = {"ps0": prev_scale, "burst_done": False}
        elif phase == "none":
            self._drop_state = None
            self._pos_scale = 1.0
            self.particle_count = int(self._config["particle_count"])

    def _phase_step(self, dt):
        """Advance the charge/lull/drop state machine. Runs every draw,
        before population management; sets the per-frame overrides
        (_pos_scale, _omega_scale, _lull_f, particle_count)."""
        pend = self._phase_pending
        if pend is not None:
            self._phase_pending = None
            if pend != self._phase:
                self._enter_phase(pend)
        self._lull_f = 0.0
        self._omega_scale = 1.0
        if self._phase == "none":
            return
        self._phase_t += dt
        # orphan watchdog: a charge/lull whose payoff never arrives
        # releases itself — the blobs ease back out, no burst
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self.phase_progress, self._phase_t,
            self._phase_done_t,
        )
        if due:
            _LOGGER.info(
                "orbits: %s watchdog release after %.1fs",
                self._phase, self._phase_t,
            )
            self._phase = "drop"
            self._phase_t = 0.0
            self.phase_progress = 0.0
            self.particle_count = int(self._config["particle_count"])
            self._drop_state = {"ps0": self._pos_scale, "burst_done": True}
            return
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        if self._phase == "charge":
            if p < CHARGE_PEAK_AT:
                f = p / CHARGE_PEAK_AT
                want = self._charge_n0 + (CHARGE_PEAK_N - self._charge_n0) * f
            else:
                f = (p - CHARGE_PEAK_AT) / (1.0 - CHARGE_PEAK_AT)
                want = CHARGE_PEAK_N + (1.0 - CHARGE_PEAK_N) * f
            self.particle_count = int(np.clip(round(want), 1, CHARGE_PEAK_N))
            self._pos_scale = 1.0
        elif self._phase == "lull":
            # fall to the center: progress-driven once it moves (hand-
            # scrubbable in the LedFX UI); the wall-clock fallback only runs
            # while progress sits at 0 so a lost ramp still falls
            f = p if p > 0.0 else min(self._phase_t / LULL_FALL_S, 1.0)
            f = f * f * (3.0 - 2.0 * f)
            self._lull_f = f
            # tiny residual radius: the blob keeps visibly swirling at the
            # center instead of freezing on a point
            self._pos_scale = 1.0 - 0.97 * f
            self._omega_scale = 1.0 - 0.6 * f
            self.particle_count = 1
        else:  # drop
            drop = self._drop_state
            if drop is None:
                drop = self._drop_state = {
                    "ps0": self._pos_scale,
                    "burst_done": False,
                }
            if not drop["burst_done"]:
                drop["burst_done"] = True
                self.particle_count = int(self._config["particle_count"])
                tracked = int(np.count_nonzero(self.p_mode[: self.n] < 2))
                missing = self.particle_count - tracked
                if missing > 0:
                    self._spawn_center_burst(0.0, 0.0, missing)
                # the big explosion: 2× more blobs that DON'T stay — they
                # blast straight off the panel during the boost window
                self._spawn_drop_ejecta(DROP_EJECTA_X * self.particle_count)
            # survivors of the lull fly back out to their orbits fast
            ps0 = drop["ps0"]
            self._pos_scale = ps0 + (1.0 - ps0) * min(
                self._phase_t / DROP_FLY_S, 1.0
            )
            self._omega_scale = 1.0 + DROP_BOOST * max(
                1.0 - self._phase_t / DROP_SETTLE_S, 0.0
            )
            if self._phase_t >= DROP_SETTLE_S:
                self._phase = "none"
                self._drop_state = None
                self._pos_scale = 1.0
                # sanctioned in-render config path (under the effect lock);
                # self-reset so an identical later drop write edges again
                self._apply_config(
                    {"phase": "none", "phase_progress": 0.0},
                    validate=False,
                    fire_event=False,
                )

    def _splat(self, buf, xs, ys, rgb, size):
        """Additively stamp a soft dot at each (xs, ys) pixel position."""
        keep = self.k_dist <= size
        k_dx = self.k_dx[keep]
        k_dy = self.k_dy[keep]
        k_w = (1.0 - self.k_dist[keep] / (size + 0.5)).astype(np.float32)
        xi = np.round(xs).astype(np.int32)
        yi = np.round(ys).astype(np.int32)
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
        w = np.broadcast_to(
            k_w[None, :], (xi.size, k_w.size)
        ).ravel()[valid]
        cells = self.r_width * self.r_height
        for channel in range(3):
            buf[..., channel] += np.bincount(
                idx, weights=w * rgb[channel], minlength=cells
            ).reshape(self.r_height, self.r_width)

    def _draw_collapse(self, dt):
        """Outgoing gather: every particle (leavers included) spirals into
        the incoming radial's center with continuing spin, pinching bright.
        Replaces the whole normal update path; renders through the same
        substep/splat/trail pipeline."""
        col = self._collapse
        n = self.n
        frac = particle_handoff.transition_progress(self._virtual)
        if frac is not None:
            s_ = float(
                np.clip(
                    (frac - col["frac0"])
                    / max(particle_handoff.GATHER_FRAC - col["frac0"], 1e-3),
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
                max((t - particle_handoff.COLLAPSE_FALLBACK_S) / 0.5, 0.0),
                1.0,
            )
        e = s_ * s_ * (3.0 - 2.0 * s_)

        half_life = 0.02 + self.trail_decay * 0.5
        self.trail *= np.float32(0.5 ** (dt / half_life))

        if n:
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
            bright = np.minimum(
                col["bright0"][:k] * (1.0 + 0.6 * e), 1.0
            ) * (1.0 - p2)
            self.p_bright[:k] = bright
            rgb = self.get_gradient_color_vectorized1d(
                col["grad0"][:k]
            ).astype(np.float32)

            snap_m = ~np.isfinite(self.p_x0[:k])
            if snap_m.any():
                self.p_x0[:k][snap_m] = x[snap_m]
                self.p_y0[:k][snap_m] = y[snap_m]
            fractions = (
                np.arange(1, SUBSTEPS + 1, dtype=np.float32) / SUBSTEPS
            )
            xs = self.p_x0[:k][:, None] + (x - self.p_x0[:k])[:, None] * fractions
            ys = self.p_y0[:k][:, None] + (y - self.p_y0[:k])[:, None] * fractions
            pxs = self.cx + xs * self.sx
            pys = self.cy + ys * self.sy

            frame = np.zeros_like(self.trail)
            for i in range(k):
                b = bright[i]
                if b <= 0.0:
                    continue
                self._splat(
                    frame,
                    pxs[i],
                    pys[i],
                    rgb[i] * (b / SUBSTEPS),
                    self.blob_size,
                )
            np.maximum(self.trail, np.minimum(frame, 255.0), out=self.trail)
            self.p_x0[:k] = x
            self.p_y0[:k] = y

        out = np.asarray(self.matrix, dtype=np.float32) + self.trail
        self.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB"
        )

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
        self.t += dt
        self._spike_cool = max(0.0, self._spike_cool - dt)
        for name in ("ring_phase", "roll_total", "t"):
            if not np.isfinite(getattr(self, name)):
                setattr(self, name, 0.0)

        virtual = self._virtual
        # held eruption: a collapsing radial predecessor owns phase 1 —
        # render decaying trails only until it has pinched out
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
                self._spawn_center_burst(
                    hold["ncx"], hold["ncy"], self.particle_count
                )
            else:
                half_life = 0.02 + self.trail_decay * 0.5
                self.trail *= np.float32(0.5 ** (dt / half_life))
                out = np.asarray(self.matrix, dtype=np.float32) + self.trail
                self.matrix = Image.fromarray(
                    np.clip(out, 0, 255).astype(np.uint8), "RGB"
                )
                return

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
                half_life = 0.02 + self.trail_decay * 0.5
                self.trail *= np.float32(0.5 ** (dt / half_life))
                out = np.asarray(self.matrix, dtype=np.float32) + self.trail
                self.matrix = Image.fromarray(
                    np.clip(out, 0, 255).astype(np.uint8), "RGB"
                )
                return

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
                px = np.where(
                    np.isfinite(self.p_x0[:n0]), self.p_x0[:n0], 0.0
                )
                py = np.where(
                    np.isfinite(self.p_y0[:n0]), self.p_y0[:n0], 0.0
                )
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

        # spike (onset) signal for the jog kicks; beats always qualify
        spike = np.clip((self.impulse - self.slow) * 3.0, 0.0, 1.0)
        if self._beat_pending:
            spike = max(spike, 0.4 + 0.5 * impulse)
            self._beat_pending = False

        self._phase_step(dt)
        self._manage_population()
        n = self.n
        if n == 0:
            return

        # ── global motion ───────────────────────────────────────────────
        jump_eff = self.speed_jump * rscale
        self.ring_phase = (
            self.ring_phase
            + self.spin
            * self.base_speed
            * direction
            * (1.0 + 0.5 * jump_eff * impulse)
            * dt
        ) % 1.0
        self.roll_total = (self.roll_total + self.gradient_spin * dt) % 1.0

        # ── per-particle dynamics ───────────────────────────────────────
        mode = self.p_mode[:n]
        tracked = mode < 2
        m = int(np.count_nonzero(tracked))

        # slot re-spacing ease (wrapped shortest way around the ring)
        target = self.p_slot[:n].astype(np.float32) / max(m, 1)
        diff = (target - self.p_slot_frac[:n] + 0.5) % 1.0 - 0.5
        self.p_slot_frac[:n] = (
            self.p_slot_frac[:n] + diff * min(1.0, dt / SLOT_EASE_S)
        ) % 1.0

        # smooth per-particle noise + reactivity gain: identical response at
        # jiggle 0, fully independent at jiggle 1
        n_r = 0.6 * np.sin(self.t * self.p_nf1[:n] + self.p_np1[:n]) + \
            0.4 * np.sin(self.t * self.p_nf2[:n] + self.p_np2[:n])
        n_w = np.sin(self.t * self.p_wf[:n] + self.p_wp[:n])
        gain = (1.0 - jiggle) + jiggle * (
            0.5 + 0.5 * np.sin(self.t * self.p_gf[:n] + self.p_gp[:n])
        )

        boost = jump_eff * impulse * gain
        omega = (
            2 * np.pi
            * self.base_speed
            * direction
            * (1.0 + jiggle * 2.5 * n_w)
            * (1.0 + boost)
            + self.p_jog[:n]
        )
        # lull slows the fall-to-center swirl; drop boosts the explosion
        omega = omega * self._omega_scale
        self.p_phase[:n] += omega * dt
        self.p_phase[:n] %= 2 * np.pi

        # jog kicks: spikes/beats bounce particles off course
        jog_eff = self.speed_jog * rscale
        if spike > 0.12 and self._spike_cool <= 0.0 and jog_eff > 0.0:
            self._spike_cool = SPIKE_COOL_S
            common = self._rng.uniform(-1.0, 1.0, 2)
            per = self._rng.uniform(-1.0, 1.0, (2, n))
            k_ang = (1.0 - jiggle) * common[0] + jiggle * per[0]
            k_rad = (1.0 - jiggle) * common[1] + jiggle * per[1]
            self.p_jog[:n] += k_ang * spike * jog_eff * 10.0
            self.p_ro[:n] += k_rad * spike * jog_eff * self.orbit_radius * 0.6
        self.p_jog[:n] *= np.float32(0.5 ** (dt / 0.12))
        self.p_ro[:n] *= np.float32(0.5 ** (dt / 0.25))

        # ── positions (normalized space) ────────────────────────────────
        # tether_scatter blends each tether from its even slot toward a fixed
        # per-particle random ring position (wrapped shortest way around)
        ring_frac = self.p_slot_frac[:n]
        if self.tether_scatter > 0.0:
            scatter_diff = (self.p_scatter[:n] - ring_frac + 0.5) % 1.0 - 0.5
            ring_frac = ring_frac + scatter_diff * self.tether_scatter
        ring_ang = (self.ring_phase + ring_frac) * 2 * np.pi
        # _pos_scale collapses the whole orbital geometry into the center
        # during a lull and releases it again on the drop
        ring_r = self.horizon_scale * self._pos_scale
        tx = ring_r * np.cos(ring_ang)
        ty = ring_r * np.sin(ring_ang)
        r_orb = (
            np.clip(
                self.orbit_radius * (1.0 - jiggle * (0.5 + 0.5 * n_r))
                + self.p_ro[:n],
                0.0,
                self.orbit_radius * 1.25,
            )
            * self._pos_scale
        )
        x = tx + r_orb * np.cos(self.p_phase[:n])
        y = ty + r_orb * np.sin(self.p_phase[:n])

        entering = mode == 1
        if entering.any():
            self.p_enter[:n][entering] += (
                dt * self.p_erate[:n][entering]
                / max(self.enter_time, 0.05)
            )
            prog = np.clip(self.p_enter[:n][entering], 0.0, 1.0)
            # ease-OUT: fly-ins and adopted gliders start moving immediately
            # and decelerate into orbit (a smoothstep start reads as a hang)
            ease = 1.0 - (1.0 - prog) ** 2
            x[entering] = self.p_ex[:n][entering] * (1.0 - ease) + x[entering] * ease
            y[entering] = self.p_ey[:n][entering] * (1.0 - ease) + y[entering] * ease
            arrived = np.flatnonzero(entering)[prog >= 1.0]
            self.p_mode[arrived] = 0

        leaving = mode == 2
        if leaving.any():
            self.p_leave[:n][leaving] += dt
            x[leaving] = self.p_x0[:n][leaving] + self.p_lvx[:n][leaving] * dt
            y[leaving] = self.p_y0[:n][leaving] + self.p_lvy[:n][leaving] * dt

        # ── color / brightness / size ───────────────────────────────────
        count = max(self.particle_count, 1)
        grad = (
            ((self.p_slot[:n].astype(np.float32) - self.color_shift) % count)
            / count
            + self.roll_total
        ) % 1.0
        # entering particles that carried a color over (handoff) morph from
        # it to their slot color as they glide in
        blend_src = self.p_grad_from[:n]
        blend = entering & np.isfinite(blend_src)
        if blend.any():
            prog = np.clip(self.p_enter[:n], 0.0, 1.0)
            gdiff = (blend_src - grad + 0.5) % 1.0 - 0.5
            grad = np.where(blend, (grad + gdiff * (1.0 - prog)) % 1.0, grad)
        # departing particles keep the color they left with
        self.p_grad[:n] = np.where(tracked, grad, self.p_grad[:n])
        rgb = self.get_gradient_color_vectorized1d(
            self.p_grad[:n]
        ).astype(np.float32)

        br_eff = self.brightness_audio * rscale
        bright = np.clip(
            (1.0 - 0.45 * min(br_eff, 1.0))
            * (1.0 + 1.2 * br_eff * impulse * gain),
            0.0,
            1.0,
        )
        # fade in over the first ~30% of the glide — an entering particle is
        # visible near its SPAWN point (e.g. the center burst) and visibly
        # travels out to its orbit, instead of materializing on arrival
        fade_in = np.where(
            entering, np.clip(self.p_enter[:n] * 3.3, 0.0, 1.0), 1.0
        )
        fade_out = np.where(
            leaving,
            np.clip(
                1.0 - self.p_leave[:n] / np.maximum(self.p_lfade[:n], 0.05),
                0.0,
                1.0,
            ),
            1.0,
        )
        bright = bright * fade_in * fade_out
        self.p_bright[:n] = bright

        # blob size eases from an adopted predecessor's size to ours over
        # the same window the particles glide into orbit
        blob = self.blob_size
        if self._size_age is not None:
            self._size_age += dt
            ease_t = max(self.enter_time, 0.05)
            if self._size_age >= ease_t:
                self._size_age = None
                self._size_from = None
            else:
                w = self._size_age / ease_t
                w = w * w * (3.0 - 2.0 * w)
                blob = (
                    self._size_from
                    + (self.blob_size - self._size_from) * w
                )
        size_eff = self.size_audio * rscale
        sizes = np.clip(
            blob * (1.0 + 0.8 * size_eff * impulse * gain),
            0.5,
            float(KERNEL_R),
        )
        if self._lull_f > 0.0:
            # the falling blob shrinks as it approaches the center
            sizes = np.clip(
                sizes * (1.0 - 0.6 * self._lull_f), 0.5, float(KERNEL_R)
            )

        # ── render ──────────────────────────────────────────────────────
        half_life = 0.02 + self.trail_decay * 0.5
        self.trail *= np.float32(0.5 ** (dt / half_life))

        # particles spawned in place this frame have no previous position —
        # snap it to the current one so they don't streak from the origin
        snap = ~np.isfinite(self.p_x0[:n])
        if snap.any():
            self.p_x0[:n][snap] = x[snap]
            self.p_y0[:n][snap] = y[snap]

        fractions = np.arange(1, SUBSTEPS + 1, dtype=np.float32) / SUBSTEPS
        xs = self.p_x0[:n][:, None] + (x - self.p_x0[:n])[:, None] * fractions
        ys = self.p_y0[:n][:, None] + (y - self.p_y0[:n])[:, None] * fractions
        pxs = self.cx + xs * self.sx
        pys = self.cy + ys * self.sy

        frame = np.zeros_like(self.trail)
        for i in range(n):
            b = bright[i]
            if b <= 0.0:
                continue
            self._splat(
                frame, pxs[i], pys[i], rgb[i] * (b / SUBSTEPS), sizes[i]
            )
        # Bright current particles over a fading history, bounded.
        np.maximum(self.trail, np.minimum(frame, 255.0), out=self.trail)

        self.p_x0[:n] = x
        self.p_y0[:n] = y

        # retire departed particles once they're fully off-panel or faded
        if leaving.any():
            off_px = np.abs(pxs[:, -1] - self.cx) > (self.r_width + 12)
            off_py = np.abs(pys[:, -1] - self.cy) > (self.r_height + 12)
            dead = leaving & (
                (self.p_leave[:n] >= self.p_lfade[:n]) | off_px | off_py
            )
            if dead.any():
                self._compact(~dead)

        out = np.asarray(self.matrix, dtype=np.float32) + self.trail
        self.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB"
        )
