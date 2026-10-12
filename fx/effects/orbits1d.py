import colorsys
import logging

import numpy as np
import voluptuous as vol

from fx.color import validate_gradient
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect
from fx.effects.strip_phase import StripPhase

_LOGGER = logging.getLogger(__name__)

CAP = 48            # particle buffer cap (count max + departing extras)
FRAG_CAP = 64       # implosion fragment buffer cap
SUBSTEPS = 3        # path sub-samples per frame (gap-free smear)
DT_MAX = 0.1
LEAVE_FADE_S = 1.2   # fade-out horizon for removed particles
SLOT_EASE_S = 0.6    # tether re-spacing ease time constant
SPIKE_COOL_S = 0.12  # min gap between jump-direction re-rolls
KERNEL_MAX = 8       # max blob radius in pixels

# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; the strip phase layer edge-detects it and calls
# _strip_phase_enter).
#
# THE STRIP PHASE LAYER, 2026-10-11 (strip phase plan phase 3 — fx/effects/
# strip_phase.py is the binding statement). The Admiral: "increase in
# brightness and activity during charge, dim and relax into black for most
# lulls, and big explosion of brightness and activity on the [drop]" — and,
# binding, "i don't want to raise the white in the charge, or on the drop".
# This strip joins the shared layer (StripPhase, first in its bases), which
# draws what the strip SHOWS on a phase (the hue-kept colour gain, the
# set-colour fill, the drop's set-colour shockwave, the lull's fade at the
# room's shared dark point, the white guard — which also keeps the
# implosion fragments' ±120° hues from adding up to white on a charge or a
# drop) and owns the phase plumbing (edge detection, the orphan watchdog,
# the drop's self-reset after DROP_SETTLE_S). What stays here is the
# effect's own choreography:
#   - the charge SWELLS to CHARGE_PEAK_N blobs over its first CHARGE_PEAK_AT
#     of progress and HOLDS there (his call 2, "swell and hold" — it used
#     to shed back to ONE by the charge's end, emptying the build just
#     before the drop);
#   - the lull drops to one blob that falls to the strip middle and shrinks,
#     landing exactly as the strip reaches the room's dark point (the
#     layer's own lull timing, `_strip_phase_lull`);
#   - the drop re-adds ALL CHARGE_PEAK_N blobs (each erupting through its
#     implosion fragments — the strip-native explosion) flying back out
#     with a spin boost, then sheds back to the scene's own count when the
#     drop settles;
#   - a flare that punches through the lull's dark springs the collapsed
#     blob back out (size and position follow the punch's envelope) with an
#     implosion burst in the blob's OWN colour (the lull has no white
#     guard, and the ±120° pair converging on the blob would add to white);
#   - on a charge or a drop the implosion pair comes from the SET (the set
#     rotated by a third) instead of the hue wheel's ±120°, which reaches
#     hues the set never has — set colours only (_phase_fragment_colours).
# The layer's ACTIVITY scales the orbit speed and the ring spin.
CHARGE_PEAK_N = 16          # particle_count's own max (strip phase plan)
CHARGE_PEAK_AT = 0.45
DROP_FLY_S = 0.4
DROP_SETTLE_S = 1.2
DROP_BOOST = 2.5

_SOA_NAMES = (
    "p_mode", "p_slot", "p_slot_frac", "p_phase", "p_dir", "p_jdir",
    "p_roff", "p_enter", "p_leave", "p_boom",
    "p_nf1", "p_nf2", "p_np1", "p_np2", "p_wf", "p_wp", "p_gf", "p_gp",
    "p_grad", "p_pos0", "p_bright",
)


def _hue_rotate(rgb, degrees):
    """Rotate an RGB color (0-255 floats) around the hue wheel."""
    h, s, v = colorsys.rgb_to_hsv(*(np.clip(rgb, 0, 255) / 255.0))
    h = (h + degrees / 360.0) % 1.0
    return np.array(colorsys.hsv_to_rgb(h, s, v), dtype=np.float32) * 255.0


class Orbits1d(StripPhase, AudioReactiveEffect, GradientEffect):
    """The Orbits particle system flattened onto a strip.

    A fixed population of particles, each tethered to an evenly-spaced point
    on the strip; the tether ring spins at a baseline speed. Particles
    oscillate around their tethers with the same jiggle wander as 2D Orbits.
    Positions wrap, so connected-end (circular) strips read as a true ring.

    Jiggle stacks onto every random decision: near 0 all particles roll the
    same outcome together, at 1 each rolls independently. On each music
    spike/beat, speed_jog is the chance a particle's speed jump runs
    BACKWARD until the next spike, and bounce_chance is the chance it
    bounces: its tether drifts backward along the strip (and its
    oscillation flips) until a later bounce turns it forward again.

    overlap_blend sets what happens where blobs overlap: 0 = no brightness
    gain (colors meet at their hue midpoint), 1 = full constructive
    interference (brightness adds).

    Newly added particles implode: two half-brightness fragments, hue-rotated
    ±120° from the particle's color, start implode_reach of the strip away on
    either side and converge on the spawn point over implode_fade seconds,
    brightening as they arrive while the particle itself fades in.

    Charge/lull/drop: the shared strip phase layer (fx/effects/
    strip_phase.py) draws the phases; this effect adds its own blob
    choreography under it (module constants above).
    """

    NAME = "Orbits Strip"
    CATEGORY = "Classic"
    # the strip phase layer's ACTIVITY (fx/effects/strip_phase.py, HOW AN
    # EFFECT JOINS, step 3): the orbit speed and the ring spin — the blob
    # COUNT is this effect's own choreography (the swell), never scaled
    STRIP_PHASE_ACTIVITY = {"base_speed": 0.5, "spin": 0.5}
    # the drop's own length: the layer self-resets the phase key after it
    STRIP_PHASE_DROP_S = DROP_SETTLE_S
    # gradient_spin supersedes gradient_roll for this effect
    HIDDEN_KEYS = ["gradient_roll"]
    # phase/phase_progress are SpotFX-driven choreography; advanced (not
    # hidden) so the arc can be hand-scrubbed in the LedFX UI for tuning.
    ADVANCED_KEYS = AudioReactiveEffect.ADVANCED_KEYS + [
        "impulse_decay",
        "color_shift",
        "implode_fade",
        "implode_reach",
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
                description="Number of particles kept alive on the strip",
                default=6,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
            vol.Optional(
                "tether_scatter",
                description="Tether spacing bias: 0 = perfectly equidistant, 1 = fully random placement",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "orbit_radius",
                description="Oscillation reach around each tether, as a fraction of the particle spacing",
                default=0.25,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.02, max=0.8)),
            vol.Optional(
                "blob_size",
                description="Particle radius in pixels",
                default=1.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=6.0)),
            vol.Optional(
                "x_offset",
                description="Rotate the whole tether ring around the strip",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "spin",
                description="Tether ring rotation speed (fraction of base speed)",
                default=0.15,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "base_speed",
                description="Base oscillation speed in cycles per second",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=2.0)),
            vol.Optional(
                "reverse",
                description="Reverse the spin direction (oscillation and ring)",
                default=False,
            ): bool,
            vol.Optional(
                "jiggle",
                description="0 = clean synced motion, 1 = independent smooth wander per particle",
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
                description="Chance (per spike/beat) that a particle's speed jump runs backward",
                default=0.3,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "bounce_chance",
                description="Chance (per spike/beat) that a particle bounces and travels backward along the strip",
                default=0.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
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
                "overlap_blend",
                description="Overlapping blobs: 0 = no brightness gain (hue midpoint), 1 = fully additive",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "implode_fade",
                description="Seconds an add-implosion takes: fragments converge while the particle fades in",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=3.0)),
            vol.Optional(
                "implode_reach",
                description="Fraction of the strip away the implosion fragments start",
                default=0.4,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=1.0)),
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
        }
    )

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        # Particle SoA + accumulators live here (NOT on_activate) so they
        # survive config patches without killing all particles.
        self.p_mode = np.zeros(CAP, dtype=np.int8)  # 0 active 1 entering 2 leaving
        self.p_slot = np.zeros(CAP, dtype=np.int16)
        self.p_slot_frac = np.zeros(CAP, dtype=np.float32)  # ring position 0..1
        self.p_phase = np.zeros(CAP, dtype=np.float32)      # oscillation angle
        self.p_dir = np.ones(CAP, dtype=np.float32)         # spin sign (bounce)
        self.p_jdir = np.ones(CAP, dtype=np.float32)        # jump sign (jog)
        # per-particle ring offset: accumulates while bounced (p_dir < 0) so
        # the tether itself travels backward along the strip
        self.p_roff = np.zeros(CAP, dtype=np.float32)
        self.p_enter = np.zeros(CAP, dtype=np.float32)      # fade-in progress
        self.p_leave = np.zeros(CAP, dtype=np.float32)      # fade-out age
        self.p_boom = np.zeros(CAP, dtype=np.int8)          # owes an explosion
        # smooth-noise oscillators: amplitude (2 bands), omega, reactivity gain
        self.p_nf1 = np.zeros(CAP, dtype=np.float32)
        self.p_nf2 = np.zeros(CAP, dtype=np.float32)
        self.p_np1 = np.zeros(CAP, dtype=np.float32)
        self.p_np2 = np.zeros(CAP, dtype=np.float32)
        self.p_wf = np.zeros(CAP, dtype=np.float32)
        self.p_wp = np.zeros(CAP, dtype=np.float32)
        self.p_gf = np.zeros(CAP, dtype=np.float32)
        self.p_gp = np.zeros(CAP, dtype=np.float32)
        self.p_grad = np.zeros(CAP, dtype=np.float32)
        self.p_pos0 = np.full(CAP, np.nan, dtype=np.float32)  # last strip pos
        self.p_bright = np.zeros(CAP, dtype=np.float32)
        # per-particle random ring position used when tether_scatter > 0
        self.p_scatter = np.zeros(CAP, dtype=np.float32)
        self._soa = tuple(getattr(self, name) for name in _SOA_NAMES) + (
            self.p_scatter,
        )
        self.n = 0
        # explosion fragments (transient sprites)
        self.f_pos = np.zeros(FRAG_CAP, dtype=np.float32)
        self.f_vel = np.zeros(FRAG_CAP, dtype=np.float32)
        self.f_age = np.zeros(FRAG_CAP, dtype=np.float32)
        self.f_life = np.zeros(FRAG_CAP, dtype=np.float32)
        self.f_rgb = np.zeros((FRAG_CAP, 3), dtype=np.float32)
        self.fn = 0
        self._booted = False
        self.t = 0.0
        self.ring_phase = 0.0
        self.roll_total = 0.0
        self.impulse = 0.0
        self.slow = 0.0
        self._beat_pending = False
        self._spike_cool = 0.0
        self._rng = np.random.default_rng()
        self.trail = None
        # charge/lull/drop choreography state (_strip_phase_enter)
        self._charge_n0 = 1
        self._pos_scale = 1.0
        self._lull_f = 0.0
        self._omega_scale = 1.0
        # the drop's fly-out (or a watchdog release's), on its own clock:
        # {"ps0": the collapse it flies out of, "t": seconds}
        self._fly = None
        self._punch_pending = False

    def config_updated(self, config):
        # NO super() call: Effect._apply_config already runs every direct
        # base's own config_updated (StripPhase, AudioReactiveEffect,
        # GradientEffect), and a second StripPhase pass on a creation write
        # would turn a stale persisted phase key into a false edge.
        self.particle_count = self._config["particle_count"]
        self.tether_scatter = self._config["tether_scatter"]
        self.orbit_radius = self._config["orbit_radius"]
        self.blob_size = self._config["blob_size"]
        self.x_offset = self._config["x_offset"]
        self.spin = self._config["spin"]
        self.base_speed = self._config["base_speed"]
        self.reverse = self._config["reverse"]
        self.jiggle = self._config["jiggle"]
        self.reactivity_scale = self._config["reactivity_scale"]
        self.speed_jump = self._config["speed_jump"]
        self.speed_jog = self._config["speed_jog"]
        self.bounce_chance = self._config["bounce_chance"]
        self.brightness_audio = self._config["brightness_audio"]
        self.size_audio = self._config["size_audio"]
        self.overlap_blend = self._config["overlap_blend"]
        self.implode_fade = self._config["implode_fade"]
        self.implode_reach = self._config["implode_reach"]
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

    def audio_data_updated(self, data):
        power = getattr(data, self.power_func)()
        impulse = self.impulse_filter.update(power)
        self.impulse = float(impulse) if np.isfinite(impulse) else 0.0
        slow = self.slow_filter.update(power)
        self.slow = float(slow) if np.isfinite(slow) else 0.0
        if data.bpm_beat_now():
            self._beat_pending = True

    def on_activate(self, pixel_count):
        if self.trail is None or len(self.trail) != pixel_count:
            self.trail = np.zeros((pixel_count, 3), dtype=np.float32)

    def _compact(self, alive):
        count = int(np.count_nonzero(alive))
        for arr in self._soa:
            arr[:count] = arr[: self.n][alive]
        self.n = count

    def _spawn(self, count):
        """Spawn `count` particles at their tethers. After boot each new one
        fades in quickly and owes an add-explosion on its first draw."""
        count = min(count, CAP - self.n)
        if count <= 0:
            return
        s = slice(self.n, self.n + count)
        rng = self._rng
        if self._booted:
            self.p_mode[s] = 1
            self.p_enter[s] = 0.0
            self.p_boom[s] = 1
        else:
            self.p_mode[s] = 0
            self.p_enter[s] = 1.0
            self.p_boom[s] = 0
        self.p_pos0[s] = np.nan
        self.p_scatter[s] = rng.random(count, dtype=np.float32)
        self.p_bright[s] = 0.0
        self.p_leave[s] = 0.0
        self.p_phase[s] = rng.uniform(0.0, 2 * np.pi, count)
        self.p_dir[s] = 1.0
        self.p_jdir[s] = 1.0
        self.p_roff[s] = 0.0
        # smooth-noise oscillator frequencies, random phases
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
        """Spawn / mark departures so mode<2 population matches
        particle_count, then (re)assign evenly-spaced ring slots."""
        tracked = np.flatnonzero(self.p_mode[: self.n] < 2)
        want = self.particle_count
        have = tracked.size
        if have < want:
            self._spawn(want - have)
            tracked = np.flatnonzero(self.p_mode[: self.n] < 2)
        elif have > want:
            doomed = self._rng.choice(tracked, size=have - want, replace=False)
            self.p_mode[doomed] = 2
            self.p_leave[doomed] = 0.0
            tracked = np.flatnonzero(self.p_mode[: self.n] < 2)
        self._booted = True
        # stable-order slot assignment; the rest ease into freed spots
        self.p_slot[tracked] = np.arange(tracked.size, dtype=np.int16)
        # fresh spawns start at their final slot position instead of easing
        fresh = tracked[~np.isfinite(self.p_pos0[tracked])]
        if fresh.size:
            self.p_slot_frac[fresh] = (
                self.p_slot[fresh].astype(np.float32) / max(tracked.size, 1)
            )

    def _spawn_fragments(self, pos, rgb, colours=None):
        """Implosion: two half-brightness fragments, hue-rotated ±120° from
        the particle color, start implode_reach away on either side and
        converge on `pos` over implode_fade seconds, brightening as they
        arrive. `colours` (two RGB colours) replaces the hue-wheel pair —
        on a phase the pair comes from the SET (_phase_fragment_colours)."""
        speed = self.implode_reach / max(self.implode_fade, 0.05)
        if colours is None:
            colours = (_hue_rotate(rgb, 120.0), _hue_rotate(rgb, -120.0))
        for direction, colour in zip((1.0, -1.0), colours):
            if self.fn >= FRAG_CAP:
                return
            i = self.fn
            self.f_pos[i] = (pos + direction * self.implode_reach) % 1.0
            self.f_vel[i] = -direction * speed
            self.f_age[i] = 0.0
            self.f_life[i] = self.implode_fade
            self.f_rgb[i] = np.clip(colour, 0, 255) * 0.5
            self.fn += 1

    def _phase_fragment_colours(self, grad):
        """On a phase (and while the drop settles) the implosion pair is
        the set rotated by a third — two of the set's OWN colours, still a
        pair either side of the particle's — instead of the hue wheel's
        ±120°, which reaches hues the set never has ("set colours only")
        and adds up to white where the pair meets its particle. None
        outside a phase: the effect's own look, unchanged."""
        if self._sp_phase == "none" and self._sp_drop_t is None:
            return None
        at = np.array([(grad + 1.0 / 3.0) % 1.0, (grad - 1.0 / 3.0) % 1.0],
                      dtype=np.float32)
        pair = self.get_gradient_color_vectorized1d(at).astype(np.float32)
        return pair[0], pair[1]

    # ── charge/lull/drop choreography ───────────────────────────────────

    def _strip_phase_enter(self, phase, prev, released):
        """The phase key edged (the strip layer's plumbing — fx/effects/
        strip_phase.py). A watchdog release of an orphaned charge/lull
        flies the blobs back out like a drop (no extra blobs)."""
        if phase == "charge":
            tracked = int(np.count_nonzero(self.p_mode[: self.n] < 2))
            self._charge_n0 = max(tracked, 1)
            self._fly = None
        elif phase == "drop":
            self._fly = {"ps0": self._pos_scale, "t": 0.0}
        elif phase == "none":
            # shed back to the scene's own count (the drop's peak, or a
            # released build, departs through the ordinary fade-out)
            self.particle_count = int(self._config["particle_count"])
            if released:
                self._fly = {"ps0": self._pos_scale, "t": 0.0}

    def _strip_phase_on_punch(self):
        """A flare punched through the lull (strip_phase): the collapsed
        blob springs back out with an implosion burst of its own colour —
        unless his "Flare punch" is 0, where the dark wins."""
        if float(self._config.get("flare_punch_strength", 1.0) or 0.0) > 0.0:
            self._punch_pending = True

    def _phase_step(self, dt):
        """This frame's choreography (module constants): the blob count,
        the collapse toward the strip middle and the spin scale."""
        self._lull_f = 0.0
        self._omega_scale = 1.0
        fly = self._fly
        if fly is not None:
            # the drop's fly-out: ease the collapse back open over
            # DROP_FLY_S, the spin boost settling over DROP_SETTLE_S — its
            # own clock, so the drop's self-reset never cuts it short
            fly["t"] += dt
            t = fly["t"]
            ps0 = fly["ps0"]
            self._pos_scale = ps0 + (1.0 - ps0) * min(t / DROP_FLY_S, 1.0)
            self._omega_scale = 1.0 + DROP_BOOST * max(
                1.0 - t / DROP_SETTLE_S, 0.0)
            if t >= DROP_SETTLE_S:
                self._fly = None
                self._pos_scale = 1.0
        phase = self._sp_phase
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        if phase == "charge":
            # swell to the peak, then HOLD it to the drop (his call 2)
            f = min(p / CHARGE_PEAK_AT, 1.0)
            want = self._charge_n0 + (CHARGE_PEAK_N - self._charge_n0) * f
            self.particle_count = int(np.clip(round(want), 1, CHARGE_PEAK_N))
            self._pos_scale = 1.0
        elif phase == "lull":
            # one blob falls to the strip middle, landing as the strip
            # reaches the room's dark point; a flare punch springs it back
            # out along its own envelope
            timing = self._strip_phase_lull()
            a = 1.0 if timing is None or timing.dark else float(timing.approach)
            f = a * a * (3.0 - 2.0 * a)
            f *= 1.0 - self._strip_phase_punch()
            self._lull_f = f
            self._pos_scale = 1.0 - 0.97 * f
            self._omega_scale = 1.0 - 0.6 * f
            self.particle_count = 1
        elif phase == "drop":
            # every blob of the swell re-added, each erupting via its
            # implosion fragments; shed back to the scene's count on "none"
            self.particle_count = CHARGE_PEAK_N

    def _stamp(self, positions, rgb, size):
        """Additive 1D stamp of one sprite's substep path; returns its own
        frame contribution (used for both the sum and max overlap buffers)."""
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
        frame = np.empty((pixel_count, 3), dtype=np.float32)
        for channel in range(3):
            frame[:, channel] = np.bincount(
                idx, weights=w * rgb[channel], minlength=pixel_count
            )
        return frame

    def render(self):
        pixel_count = self.pixel_count
        if self.trail is None or len(self.trail) != pixel_count:
            self.trail = np.zeros((pixel_count, 3), dtype=np.float32)

        dt = min(self.passed, DT_MAX)
        if not np.isfinite(dt) or dt <= 0:
            dt = 1.0 / 60.0
        self.t += dt
        self._spike_cool = max(0.0, self._spike_cool - dt)
        for name in ("ring_phase", "roll_total", "t"):
            if not np.isfinite(getattr(self, name)):
                setattr(self, name, 0.0)

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
        ring_vel = (
            self.spin
            * self.base_speed
            * direction
            * (1.0 + 0.5 * jump_eff * impulse)
        )
        self.ring_phase = (self.ring_phase + ring_vel * dt) % 1.0
        self.roll_total = (self.roll_total + self.gradient_spin * dt) % 1.0
        # bounced particles (p_dir < 0) drift the ring the OPPOSITE way:
        # their offset cancels the shared ring motion twice over, so the
        # tether — and the particle — visibly travels backward until the
        # next bounce flips it forward again
        back = self.p_dir[: self.n] < 0.0
        if back.any():
            self.p_roff[: self.n][back] = (
                self.p_roff[: self.n][back] - 2.0 * ring_vel * dt
            ) % 1.0

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

        # spike/beat re-rolls — jiggle stacks onto every random decision:
        # near 0 one shared roll decides for the whole field, at 1 each
        # particle rolls independently.
        if spike > 0.12 and self._spike_cool <= 0.0:
            self._spike_cool = SPIKE_COOL_S
            rng = self._rng

            def blended_roll():
                shared = rng.random()
                per = rng.random(n)
                return (1.0 - jiggle) * shared + jiggle * per

            # jog: chance the speed jump runs backward until the next spike
            jog_p = min(self.speed_jog * rscale, 1.0)
            self.p_jdir[:n] = np.where(blended_roll() < jog_p, -1.0, 1.0)
            # bounce: chance the oscillation direction flips permanently
            if self.bounce_chance > 0.0:
                flip = blended_roll() < self.bounce_chance
                self.p_dir[:n][flip] *= -1.0

        boost = jump_eff * impulse * gain
        omega = (
            2 * np.pi
            * self.base_speed
            * direction
            * self.p_dir[:n]
            * (1.0 + jiggle * 2.5 * n_w)
            * (1.0 + boost * self.p_jdir[:n])
        )
        # lull slows the fall-to-center; drop boosts the explosion
        omega = omega * self._omega_scale
        self.p_phase[:n] += omega * dt
        self.p_phase[:n] %= 2 * np.pi

        # ── positions (strip fraction, wraps) ───────────────────────────
        count = max(self.particle_count, 1)
        # oscillation amplitude scales with particle spacing so orbit_radius
        # keeps the same feel at any density
        amp_base = self.orbit_radius / count
        ring_frac = self.p_slot_frac[:n]
        if self.tether_scatter > 0.0:
            scatter_diff = (self.p_scatter[:n] - ring_frac + 0.5) % 1.0 - 0.5
            ring_frac = ring_frac + scatter_diff * self.tether_scatter
        tether = (
            self.ring_phase
            + self.p_roff[:n]
            + ring_frac
            + (self.x_offset - 0.5)
        ) % 1.0
        amp = amp_base * (1.0 - jiggle * (0.5 + 0.5 * n_r))
        pos = (tether + amp * np.cos(self.p_phase[:n])) % 1.0
        if self._pos_scale < 1.0:
            # lull: everything collapses toward the strip middle (shortest
            # way around the wrap); the drop eases it back out
            off = (pos - 0.5 + 0.5) % 1.0 - 0.5
            pos = (0.5 + off * self._pos_scale) % 1.0

        entering = mode == 1
        if entering.any():
            # the particle materializes in step with its implosion
            self.p_enter[:n][entering] += dt / max(self.implode_fade, 0.05)
            arrived = np.flatnonzero(entering)[
                self.p_enter[:n][entering] >= 1.0
            ]
            self.p_mode[arrived] = 0

        leaving = mode == 2
        if leaving.any():
            self.p_leave[:n][leaving] += dt

        # ── color / brightness / size ───────────────────────────────────
        grad = (
            ((self.p_slot[:n].astype(np.float32) - self.color_shift) % count)
            / count
            + self.roll_total
        ) % 1.0
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
        # the oscillation's "radial" half shows as a subtle depth shimmer
        bright = bright * (0.82 + 0.18 * np.sin(self.p_phase[:n]))
        fade_in = np.where(
            entering, np.clip(self.p_enter[:n], 0.0, 1.0), 1.0
        )
        fade_out = np.where(
            leaving,
            np.clip(1.0 - self.p_leave[:n] / LEAVE_FADE_S, 0.0, 1.0),
            1.0,
        )
        bright = bright * fade_in * fade_out
        self.p_bright[:n] = bright

        size_eff = self.size_audio * rscale
        sizes = np.clip(
            self.blob_size * (1.0 + 0.8 * size_eff * impulse * gain),
            0.5,
            float(KERNEL_MAX),
        )
        if self._lull_f > 0.0:
            # the falling blob shrinks as it nears the middle
            sizes = np.clip(
                sizes * (1.0 - 0.6 * self._lull_f), 0.5, float(KERNEL_MAX)
            )

        # fire the add-implosions now that positions and colors are known
        boom = np.flatnonzero(self.p_boom[:n] > 0)
        for i in boom:
            self._spawn_fragments(
                float(pos[i]), rgb[i],
                self._phase_fragment_colours(float(self.p_grad[i])))
        if boom.size:
            self.p_boom[boom] = 0
        if self._punch_pending:
            # a flare punched through the lull's dark: the collapsed blob's
            # own implosion burst, in its own colour
            self._punch_pending = False
            if self._sp_phase == "lull":
                for i in np.flatnonzero(tracked):
                    self._spawn_fragments(float(pos[i]), rgb[i],
                                          (rgb[i], rgb[i]))

        # ── fragments ───────────────────────────────────────────────────
        fn = self.fn
        fpos0 = self.f_pos[:fn].copy()
        if fn:
            self.f_pos[:fn] = (self.f_pos[:fn] + self.f_vel[:fn] * dt) % 1.0
            self.f_age[:fn] += dt

        # ── render ──────────────────────────────────────────────────────
        half_life = 0.02 + self.trail_decay * 0.5
        self.trail *= np.float32(0.5 ** (dt / half_life))

        # sprites spawned this frame have no previous position — snap it so
        # they don't streak from strip origin
        snap = ~np.isfinite(self.p_pos0[:n])
        if snap.any():
            self.p_pos0[:n][snap] = pos[snap]

        fractions = np.arange(1, SUBSTEPS + 1, dtype=np.float32) / SUBSTEPS
        # wrap-aware smear: interpolate along the shortest way around
        delta = (pos - self.p_pos0[:n] + 0.5) % 1.0 - 0.5
        paths = (self.p_pos0[:n][:, None] + delta[:, None] * fractions) % 1.0

        # Per-sprite stamps feed two buffers: the additive sum and the
        # per-pixel max of any single sprite. overlap_blend then interpolates
        # the output brightness between max (0) and sum (1) while keeping the
        # summed chroma — so 0 lands overlaps on the hue midpoint.
        sum_buf = np.zeros((pixel_count, 3), dtype=np.float32)
        max_buf = np.zeros((pixel_count, 3), dtype=np.float32)
        for i in range(n):
            b = bright[i]
            if b <= 0.0:
                continue
            f = self._stamp(paths[i], rgb[i] * b, sizes[i])
            sum_buf += f
            np.maximum(max_buf, f, out=max_buf)
        if fn:
            fdelta = (self.f_pos[:fn] - fpos0 + 0.5) % 1.0 - 0.5
            fpaths = (fpos0[:, None] + fdelta[:, None] * fractions) % 1.0
            # implosion fragments brighten as they converge
            flife = np.clip(
                self.f_age[:fn] / np.maximum(self.f_life[:fn], 1e-3),
                0.0,
                1.0,
            )
            for i in range(fn):
                if flife[i] <= 0.0:
                    continue
                f = self._stamp(
                    fpaths[i], self.f_rgb[i] * flife[i], self.blob_size
                )
                sum_buf += f
                np.maximum(max_buf, f, out=max_buf)

        blend = self.overlap_blend
        if blend < 1.0:
            sum_lum = sum_buf.max(axis=1)
            max_lum = max_buf.max(axis=1)
            target = max_lum + blend * (sum_lum - max_lum)
            scale = np.where(sum_lum > 1e-6, target / np.maximum(sum_lum, 1e-6), 0.0)
            frame = sum_buf * scale[:, None]
        else:
            frame = sum_buf

        # Bright current sprites over a fading history, bounded.
        np.maximum(self.trail, np.minimum(frame, 255.0), out=self.trail)

        self.p_pos0[:n] = pos

        # retire dead fragments and departed particles
        if fn:
            alive_f = self.f_age[:fn] < self.f_life[:fn]
            if not alive_f.all():
                keep = int(np.count_nonzero(alive_f))
                for arr in (
                    self.f_pos, self.f_vel, self.f_age, self.f_life,
                ):
                    arr[:keep] = arr[:fn][alive_f]
                self.f_rgb[:keep] = self.f_rgb[:fn][alive_f]
                self.fn = keep
        if leaving.any():
            dead = leaving & (self.p_leave[:n] >= LEAVE_FADE_S)
            if dead.any():
                self._compact(~dead)

        self.pixels = self.trail.copy()
