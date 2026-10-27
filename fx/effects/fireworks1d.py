import logging

import numpy as np
import voluptuous as vol

import fx.effects.pre_drop as pre_drop
from fx.color import validate_gradient
from fx.effects import phase_grammar, strip_phase
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect
from fx.effects.strip_phase import StripPhase

_LOGGER = logging.getLogger(__name__)

CAP = 96            # particle buffer cap (2 per firework)
SUBSTEPS = 3        # path sub-samples per frame (gap-free smear)
DT_MAX = 0.1
FADE_IN_S = 0.05
KERNEL_MAX = 8      # max blob radius in pixels

# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; the strip phase layer edge-detects it and calls
# _strip_phase_enter). Same arc as 2D Fireworks: the launch rate climbs
# through the charge; the lull goes dark except two slow rockets crossing
# from the strip ends past the middle, with trails; the drop explodes each
# into giant pairs in its own color, then a shower of ordinary fireworks
# keeps launching through the payoff's afterglow, easing back to the
# ordinary show (the drop tail).
#
# THE STRIP PHASE LAYER, 2026-10-11 (strip phase plan phase 3 — fx/effects/
# strip_phase.py is the binding statement). The Admiral: "increase in
# brightness and activity during charge, dim and relax into black for most
# lulls, and big explosion of brightness and activity on the [drop]" — and,
# binding, "i don't want to raise the white in the charge, or on the drop".
# This strip joins the shared layer (StripPhase, first in its bases), which
# draws what the strip SHOWS on a phase (hue-kept colour gain, set-colour
# fill, the drop's set-colour shockwave, the lull's fade at the room's dark
# point, the white guard — which also keeps overlapping fireworks from
# adding up to white on a charge or a drop) and owns the phase plumbing
# (edge detection, the orphan watchdog, the drop's self-reset after
# DROP_SETTLE_S). The effect's own choreography, retuned:
#   - the charge no longer SLOWS or SHORTENS its fireworks (CHARGE_SLOW and
#     CHARGE_SHORT are 0 — a slower, shorter burst read as LESS going on);
#   - "more fireworks": his scene caps the strip at max_blobs 6, which
#     silently clipped the charge's launch multiplier to 3 fireworks in
#     flight, so the charge adds an UNCAPPED launch rate rising 0 ->
#     CHARGE_LAUNCH_RATE_MAX across the build (the drop tail's own
#     ignore_cap shape — such fireworks never occupy the cap either);
#   - the drop's shower is heavier (DROP_TAIL_RATE 8 -> 12/s);
#   - the lull's two rockets are the ONE thing a strip lull keeps lit (his
#     call 3): the layer fades the strip to this effect's own `lull_ember`
#     default (LULL_EMBER, 12%) at the dark point, so the rockets cross the
#     dark as faint embers and explode on the drop. Their own dimming
#     (LULL_ROCKET_FADE) is retired — the layer's fade is the one dimmer.
# A flare in the lull's dark needs nothing here: the Firework Burst flare
# is its own punch. The layer's ACTIVITY scales the launches (spawn rate,
# beat burst — never the density cap) and the burst speed.
CHARGE_SPAWN_X = 5.0
CHARGE_SLOW = 0.0
CHARGE_SHORT = 0.0
CHARGE_LAUNCH_RATE_MAX = 8.0   # uncapped fireworks/s at p=1 (plan phase 3)
LULL_ROCKETS = 2
LULL_FLIGHT_S = 4.0
LULL_EMBER = 0.12              # the strip's own lull_ember default
DROP_SETTLE_S = 0.9
PAYOFF_SPEED = 1.8
PAYOFF_LIFE = 1.5
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
DROP_TAIL_RATE = 12.0          # strip phase plan phase 3 (was 8, the 2D's)
DROP_TAIL_S = 2.5

# THE PRE-DROP (fx/effects/pre_drop.py is the binding statement; predrop
# plan step 9, report 3.5: "like the crystal: dark, then on the pre-drop two
# rockets fire from the ends in the new colours and burst on the drop" — the
# crystal Fireworks' own look, fx/effects/fireworks.py). A lull TOLD its drop
# has a pre-drop launches no rockets at its start: the strip goes dark (the
# ordinary show already pauses in a lull, so only what was flying fades out
# under the layer's fade), truly black for the breath-hold right before the
# pre-drop (SpotFX ends the breath exactly on it; whatever is still fading
# is gone, and a flare landing in the breath is swallowed), then the SAME
# two rockets fire ON the pre-drop from the strip's ends and fly the
# pre-drop-to-drop gap, bursting on the drop (_rocket_payoff, unchanged).
# The layer lifts the lull's 12% ember for them (_strip_phase_pre_drop_lift)
# so they fly bright, as the crystal's do; they dim over the flight by the
# crystal's own rule (0.3125 a second, never more than 0.75 — so a long
# flight dims and the lull's light stays low). One look serves both kinds.
# The shared layer's twinkle is not this strip's look. An untold lull is
# today's, byte for byte.
PRE_DROP_LOOK = "rockets"
PRE_DROP_ROCKET_FADE_PER_S = 0.3125
PRE_DROP_ROCKET_FADE_MAX = 0.75


def pre_drop_rocket_fade(gap_s: float) -> float:
    """What a pre-drop rocket loses over a flight of `gap_s` seconds."""
    return min(PRE_DROP_ROCKET_FADE_MAX,
               PRE_DROP_ROCKET_FADE_PER_S * max(0.0, gap_s))


class Fireworks1d(StripPhase, AudioReactiveEffect, GradientEffect):
    """Fireworks flattened onto a strip: each firework spawns TWO particles
    at a random position that race away from each other, trailing and
    fading as they go (like a removed Orbits Strip particle). Both share
    one color, picked at random from the gradient per firework. Volume
    drives brightness and launch speed; spawn pacing mirrors the 2D
    Fireworks (spawn_rate + beat_burst + spawn_audio, capped by max_blobs).
    Positions wrap, so connected-end strips read as a true ring. No
    center weighting — origins are uniform along the strip.

    Charge/lull/drop: the shared strip phase layer (fx/effects/
    strip_phase.py) draws the phases; this effect adds its own launches,
    rockets and payoff under it (module constants above).
    """

    NAME = "Fireworks Strip"
    CATEGORY = "Classic"
    # the strip phase layer's ACTIVITY (fx/effects/strip_phase.py, HOW AN
    # EFFECT JOINS, step 3): more launches and faster bursts. Not the
    # density cap (max_blobs is his scene's own call; the charge's extra
    # fireworks come from the uncapped launch rate instead).
    STRIP_PHASE_ACTIVITY = {"spawn_rate": 1.0, "beat_burst": 1.0,
                            "burst_speed": 0.3}
    # the lull keeps the rockets as embers (his call 3; module constants)
    STRIP_PHASE_DEFAULTS = {"lull_ember": LULL_EMBER}
    # the drop's own length: the layer self-resets the phase key after it
    STRIP_PHASE_DROP_S = DROP_SETTLE_S
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
            # the layer's tunables carrying this effect's own defaults
            **strip_phase.tunable_fields(**STRIP_PHASE_DEFAULTS),
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
        # 1.0 = spawned past the density cap (payoff, flare burst, drop
        # tail, lull rockets): never occupies max_blobs, so the ordinary
        # show keeps launching underneath — see _spawn_firework
        self.f_nocap = np.zeros(CAP, dtype=np.float32)
        self.n = 0
        self.spawn_acc = 0.0
        self.impulse = 0.0
        self._beat_pending = False
        self._rng = np.random.default_rng()
        self.trail = None
        # charge/lull/drop choreography state (_strip_phase_enter)
        self._rocket_path = None
        self._pspawn = 1.0
        self._pspeed = 1.0
        self._plife = 1.0
        self._tail_t = None
        self._tail_rate = 0.0
        self._tail_acc = 0.0
        self._charge_acc = 0.0

    def config_updated(self, config):
        # NO super() call: Effect._apply_config already runs every direct
        # base's own config_updated (StripPhase, AudioReactiveEffect,
        # GradientEffect), and a second StripPhase pass on a creation write
        # would turn a stale persisted phase key into a false edge.
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
            self.f_rocket, self.f_nocap,
        ):
            arr[:count] = arr[: self.n][alive]
        self.n = count

    def _spawn_firework(self, pos=None, grad=None, bright=None,
                        speed_mult=1.0, life_mult=1.0, ignore_cap=False):
        """Two particles from one point, racing apart, one color.
        ignore_cap bypasses max_blobs (the drop payoff must always land)
        and such particles never occupy it either (f_nocap) — they layer
        on top of the ordinary show rather than pausing it for as long as
        they live."""
        n = self.n
        if ignore_cap:
            room = CAP - n
        else:
            occupied = n - int(np.count_nonzero(self.f_nocap[:n]))
            room = min(self.max_blobs, CAP) - occupied
        if room < 2 or CAP - n < 2:
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
        self.f_nocap[s] = 1.0 if ignore_cap else 0.0
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
        self.f_nocap[s] = 1.0
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
        clk = self._strip_phase_pre_drop()
        if clk is not None and clk.segment == "pre_drop":
            # THE PRE-DROP's rockets fly the pre-drop-to-drop gap on the
            # layer's own clock, dimming by the crystal's rule
            f = clk.frac
            fade = pre_drop_rocket_fade(pre_drop.gap_s(self._config))
            self.f_bright[idx] = 1.0 - fade * f
        else:
            p = float(np.clip(self.phase_progress, 0.0, 1.0))
            f = p if p > 0.0 else min(self._sp_t / LULL_FLIGHT_S, 1.0)
        ease = 1.0 - (1.0 - f) ** 2
        self.f_pos[idx] = path["s"][:m] + (path["e"][:m] - path["s"][:m]) * ease

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

    def _strip_phase_enter(self, phase, prev, released):
        """The phase key edged (the strip layer's plumbing — fx/effects/
        strip_phase.py): a lull launches its rockets, a drop explodes them
        and starts its shower, leaving a lull any other way (or the
        watchdog releasing an orphaned one) burns them out."""
        self._charge_acc = 0.0
        if phase == "lull":
            # a lull told a pre-drop stays dark: its rockets fire on the
            # pre-drop instead (_pre_drop_step)
            if not pre_drop.told(self._config):
                self._launch_rockets()
        elif phase == "drop":
            self._rocket_payoff()
            self._tail_t = 0.0
        elif prev == "lull":
            n = self.n
            idx = np.flatnonzero(self.f_rocket[:n] > 0.0)
            if idx.size:
                self.f_life[idx] = self.f_age[idx] + 0.4
            self._rocket_path = None

    def _strip_phase_pre_drop_lift(self):
        """THE PRE-DROP (module constants): the rockets fly the gap at full,
        so the layer lifts the lull's ember for it."""
        clk = self._strip_phase_pre_drop()
        return clk is not None and clk.segment == "pre_drop"

    def _pre_drop_step(self):
        """THE PRE-DROP's look (module constants): runs only on a lull TOLD
        a pre-drop — every other frame returns 1.0 before touching anything,
        so a lull without one is today's, byte for byte. Returns the gain on
        the strip this frame: the breath-hold's ease into its black, 0.0
        through the breath, 1.0 otherwise."""
        clk = self._strip_phase_pre_drop()
        if clk is None:
            return 1.0
        if clk.segment == "breath":
            if clk.edge:
                # true black: whatever is still fading from before the lull
                # is gone before the rockets fire
                self.n = 0
                if self.trail is not None:
                    self.trail[...] = 0.0
                self._rocket_path = None
            self._burst_pending = 0     # a flare in the breath is swallowed
            return 0.0
        if clk.segment == "pre_drop":
            if clk.edge:
                self._launch_rockets()
            return 1.0
        return phase_grammar.breath_gain(self._config, self._sp_t)

    def _phase_step(self, dt):
        """This frame's choreography: the charge's launch multipliers and
        its uncapped launch rate (fireworks/s, returned), and the drop
        tail's clock."""
        self._pspawn = 1.0
        self._pspeed = 1.0
        self._plife = 1.0
        self._tail_rate = self._drop_tail_step(dt)
        if self._sp_phase != "charge":
            return 0.0
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        self._pspawn = 1.0 + CHARGE_SPAWN_X * p
        self._pspeed = 1.0 - CHARGE_SLOW * p
        self._plife = 1.0 - CHARGE_SHORT * p
        return CHARGE_LAUNCH_RATE_MAX * p

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

        charge_rate = self._phase_step(dt)
        pd_gain = self._pre_drop_step()

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

        if self._sp_phase == "lull":
            # guided rocket motion (positions set directly; f_pos0 above
            # gives them their motion smear + trail)
            self._phase_rockets()

        # ── spawn ───────────────────────────────────────────────────────
        # paused during a lull: the dark strip belongs to the rockets
        if self._sp_phase != "lull":
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
            # drop tail: the post-payoff shower, ordinary fireworks at an
            # easing rate, landed regardless of the density cap (which the
            # ordinary show itself may be saturating)
            if self._tail_rate > 0.0:
                self._tail_acc += self._tail_rate * dt
                tail = int(self._tail_acc)
                self._tail_acc -= tail
                for _ in range(tail):
                    self._spawn_firework(ignore_cap=True)
            else:
                self._tail_acc = 0.0
            # the charge's uncapped launches ("more fireworks" past his
            # density cap, the tail's own ignore_cap shape)
            if charge_rate > 0.0:
                self._charge_acc += charge_rate * dt
                extra = int(self._charge_acc)
                self._charge_acc -= extra
                for _ in range(extra):
                    self._spawn_firework(ignore_cap=True)
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

        if pd_gain != 1.0:
            # THE PRE-DROP's breath: the ease into its black, then black
            self.pixels = self.trail * np.float32(pd_gain)
        else:
            self.pixels = self.trail.copy()
