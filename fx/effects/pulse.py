"""Pulse — a one-colour light that pulses on hits (SpotFX-authored effect).

Built for the Singles (the 17 Hue bulbs and the two one-pixel WLEDs), where
Power runs at ONE pixel and is mostly inert: its sparks and bass overlay
never fire and its brightness only moves between ~0.64 and ~0.71
(single-led-power plan, phase 1, 2026-10-06). Pulse treats every pixel as
one light of ONE colour and moves its brightness on purpose.

WHAT IT DOES, frame by frame

- HIT DETECTOR (live audio, causal, per audio frame). Signal = lows power +
  2 x the mean of the virtual's own melbank ("bass weighted": bass first, but
  piano and voice still make hits so calm songs move), or lows power alone
  ("bass only"). A slow follower tracks the recent level, a decaying peak
  (PEAK_MEMORY_S) tracks the recent hit size. A hit fires when the signal is
  more than `hit_sensitivity` x the recent peak above the recent level and
  still rising, at most once per REFRACTORY_S. Each hit gets a STRENGTH
  (excess / recent peak) and a SHARPNESS (one-frame rise / SHARP_REF of the
  recent peak). Hits are measured against the music's own recent level, not
  against full volume — that is what keeps quiet songs visible.
- RISE. Linear in eye scale, from the level at the hit to its peak, over
  lerp(rise_soft_ms, rise_sharp_ms, sharpness x sqrt(strength)). The sharp
  end (16 ms) is one frame at 60 fps. Peak = strength ** PEAK_EXP. A hit
  whose sound keeps growing raises its peak but keeps its deadline: the
  rise time is the rise time, however the peak moves.
- FADE. Exponential, reaching 10% in `fade_beats x beat`, with fade_beats =
  lerp(fade_beats_calm, fade_beats_intense, energy). Counted in BEATS so it
  follows tempo.
- LEVEL (eye scale, 0 = black, 1 = full) = rest(energy) + depth(energy) x
  envelope, with rest = lerp(rest_calm, rest_intense, energy) and depth =
  lerp(depth_calm, depth_intense, energy ** DEPTH_EXP), and a pulse never
  smaller than `min_pulse` once it is under way (dim bulbs have few steps).
- OUTPUT = colour x level ** gamma. `gamma` converts the eye's scale to the
  value sent; it is an effect setting, and each Singles virtual is ONE device
  type (`hues` = Hue only, `single-color-effect` = the two WLEDs), so it is
  per device type in practice. The camera measurement is what tunes it.
- ONE COLOUR, NO BACKGROUND. The colour is the first colour of `gradient`
  (what the compiler and the colour journey already write, and what Power
  showed at one pixel). The base background layer is switched off
  structurally (`_refresh_bg_render_state`), so a colour set's Singles
  background colour can never paint under it; the resting glow is the same
  colour, dimmer. The base `brightness` still multiplies the result (a
  dimmer, after gamma).

THE FLASH-RATE LIMIT. Full-depth flashes are capped at about
`max_flash_rate` (3) a second, for comfort and photosensitive safety. It is a
LUMINANCE BUDGET: each hit costs its rise in delivered light (level ** gamma,
0..1, so a black-to-full flash costs 1.0), and the rises of all hits in any
1-second window may not sum past `max_flash_rate`. A hit that would overspend
is shrunk to what is left (to nothing if nothing is). Calm pulses cost little
and are never touched; dense intense passages are. A drop is never shrunk
but its burst is spent from the same budget, so hits right after it are.
This is the plan's rule ("about three full-depth flashes a second"), not
WCAG's stricter count of every >=10% flash; that would cap fast music at
three pulses a second whatever their size.

INPUTS THE ENGINE PUSHES (phase 2) — hooks with safe defaults:
- `energy` (0..1, default 0.5): section intensity, pushed by SPECTRA's Pulse
  feed (spectra/services/pulse_feed.py) at each section edge and carried in
  the scene fire that installs the effect. The effect eases toward a new
  value over ENERGY_SLEW_S so the light's character never snaps.
- `beat_ms` (default 0 = unknown): beat length, from the song's analysed
  tempo (same feed). Unknown falls back to the live pipeline's tempo when it
  reads 60-200 bpm, else 500 ms (120 bpm).
- `phase` + `phase_progress`: the shared charge/lull/drop keys every phase
  effect takes (fx/device_model.PHASE_EFFECTS), driven by SPECTRA's response
  engine on the same ramp as every other phase effect, so a lull reaches
  black as the crystal and strips arrive. Edge-detected in config_updated,
  consumed in render, orphan-watched by particle_handoff.phase_release_due.
  charge: the rest level climbs to `charge_top` (smoothstep of progress),
  hits keep landing on top (never less than CHARGE_MIN_DEPTH), fades
  shorten to CHARGE_FADE_X. lull: the level the light had at lull entry is
  multiplied by 1 - smoothstep(progress), so it reaches black exactly when
  the ramp completes (the same clock the other lights use). drop: begins ON
  its first frame at `drop_burst` with a `drop_white` mix, settles over
  `drop_settle_beats`, then the phase key self-resets to "none" so an
  identical later write edges again. A charge or lull that ends without a
  drop eases back over EXIT_BLEND_S instead of snapping.

State that must survive config writes lives in _init_state (created once);
config_updated only edge-detects the phase, because Effect._apply_config
runs it on EVERY write and on EVERY frame of a param tween.
"""

import collections
import logging
import math

import numpy as np
import voluptuous as vol

import fx.effects.particle_handoff as particle_handoff
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect

_LOGGER = logging.getLogger(__name__)

LN10 = math.log(10.0)
DT_MAX = 0.1                 # render dt clamp (a stalled frame never jumps)
AUDIO_RATE_DEFAULT = 60.0    # audio callbacks per second (the stock 60 fps)

# hit detector (the plan prototype's numbers; per 60 Hz audio frame)
SLOW_RISE_ALPHA = 0.10       # recent-level follower, signal above it
SLOW_FALL_ALPHA = 0.03       # recent-level follower, signal below it
PEAK_MEMORY_S = 6.0          # recent-peak memory
PEAK_FLOOR = 0.03            # recent peak never reads below this
RISE_MIN_FRAC = 0.05         # a hit must still be rising by this x peak
SHARP_REF = 0.6              # one-frame rise of SHARP_REF x peak = sharpest
REFRACTORY_S = 0.110         # at most one hit per this
PEAK_EXP = 0.7               # envelope peak = strength ** PEAK_EXP

# envelope -> level
DEPTH_EXP = 1.2              # depth = lerp(calm, intense, energy ** DEPTH_EXP)
MIN_PULSE_ENV = 0.05         # min_pulse applies once the envelope exceeds this
ENERGY_SLEW_S = 2.0          # energy eases toward a new value (time constant)
DEFAULT_BEAT_S = 0.5         # 120 bpm when no tempo is known
LIVE_BPM_RANGE = (60.0, 200.0)

# flash-rate limit
FLASH_WINDOW_S = 1.0

# charge / lull / drop
CHARGE_DEPTH_ADD = 0.2       # pulses grow by this much over a charge ...
CHARGE_MIN_DEPTH = 0.12      # ... and never shrink below this as rest climbs
CHARGE_FADE_X = 0.55         # fades shorten to this fraction by charge end
EXIT_BLEND_S = 1.0           # charge/lull ending without a drop eases back
BURST_DONE = 0.01            # drop burst below this = settled

HIT_LOG_LEN = 4096


def _lerp(a, b, t):
    return a + (b - a) * t


def _smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def _per_frame(alpha_60, dt):
    """A per-60-Hz-frame smoothing factor, rescaled to step `dt`."""
    return 1.0 - (1.0 - alpha_60) ** (dt * 60.0)


class PulseAudioEffect(AudioReactiveEffect, GradientEffect):
    NAME = "Pulse"
    CATEGORY = "Classic"
    # One light, one colour: the background layer is off by construction,
    # and blur/flip/mirror/gradient_roll mean nothing to a single light.
    HIDDEN_KEYS = [
        "background_color",
        "background_brightness",
        "background_mode",
        "blur",
        "flip",
        "mirror",
        "gradient_roll",
    ]
    # Engine-driven hooks: advanced (not hidden) so they can be scrubbed by
    # hand while tuning.
    ADVANCED_KEYS = AudioReactiveEffect.ADVANCED_KEYS + [
        "min_pulse",
        "max_flash_rate",
        "energy",
        "beat_ms",
        "phase",
        "phase_progress",
    ]

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "rest_calm",
                description="Resting level between hits in calm music (eye scale)",
                default=0.40,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "rest_intense",
                description="Resting level between hits in intense music (eye scale)",
                default=0.22,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "depth_calm",
                description="How far a full-size hit lifts the light in calm music",
                default=0.10,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "depth_intense",
                description="How far a full-size hit lifts the light in intense music",
                default=0.78,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "fade_beats_calm",
                description="Beats for a pulse to fall to a tenth, calm music",
                default=1.6,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=8.0)),
            vol.Optional(
                "fade_beats_intense",
                description="Beats for a pulse to fall to a tenth, intense music",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=8.0)),
            vol.Optional(
                "rise_soft_ms",
                description="Rise time of a soft hit (ms)",
                default=160.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1000.0)),
            vol.Optional(
                "rise_sharp_ms",
                description="Rise time of a sharp, hard hit (ms; 16 = one frame)",
                default=16.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1000.0)),
            vol.Optional(
                "hit_sensitivity",
                description="How far above the recent level a sound must jump to count as a hit (fraction of the recent peak)",
                default=0.22,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.02, max=1.0)),
            vol.Optional(
                "hit_source",
                description="Which sound makes hits",
                default="bass weighted",
            ): vol.In(["bass weighted", "bass only"]),
            vol.Optional(
                "min_pulse",
                description="Smallest visible pulse (eye scale)",
                default=0.05,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.5)),
            vol.Optional(
                "max_flash_rate",
                description="Full-depth flashes allowed per second",
                default=3.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=20.0)),
            vol.Optional(
                "gamma",
                description="Bulb curve: converts eye-scale brightness to the value sent",
                default=2.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=4.0)),
            vol.Optional(
                "charge_top",
                description="Resting level at the end of a charge (eye scale)",
                default=0.80,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "drop_burst",
                description="Brightness of the drop's burst (eye scale)",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "drop_white",
                description="White mixed into the drop's burst",
                default=0.45,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "drop_settle_beats",
                description="Beats for the drop's burst to settle",
                default=2.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=16.0)),
            vol.Optional(
                "energy",
                description="Section intensity, 0 calm to 1 intense (pushed by SpotFX)",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "beat_ms",
                description="Beat length in ms, 0 = use the live tempo (pushed by SpotFX)",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=4000.0)),
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

    # ── state ────────────────────────────────────────────────────────────

    def _init_state(self):
        """Envelope/detector state, created ONCE (config_updated runs on every
        write and every tween frame — it must never reset any of this)."""
        cfg = self._config
        # detector (audio clock)
        self._audio_t = 0.0
        self._primed = False
        self._slow = 0.0
        self._prev = 0.0
        self._peak = PEAK_FLOOR
        self._last_hit = -1e9
        self._live_bpm = 0.0
        self.last_signal = 0.0
        # envelope (render clock)
        self._env = 0.0
        self._target = 0.0
        self._hit_cap = 1.0
        self._attack_v = 0.0
        self._attack_left = 0.0
        self._attacking = False
        self._energy_live = float(cfg.get("energy", 0.5))
        self._burst = 0.0
        self._blend_from = None
        self._blend_t = 0.0
        self._rest = 0.0
        self._lull_from = 0.0
        # phase (creation baseline: a stale persisted phase never edge-fires)
        self._phase = "none"
        self._phase_t = 0.0
        self._phase_done_t = None
        self._phase_pending = None
        cfg["phase"] = "none"
        cfg["phase_progress"] = 0.0
        # flash budget: deque of [audio_t, delivered-light rise]
        self._flash_window = collections.deque()
        self._hit_entry = [0.0, 0.0]
        # diagnostics (read by tests and the check script)
        self.level = 0.0
        self.white = 0.0
        self.hits = collections.deque(maxlen=HIT_LOG_LEN)

    def config_updated(self, config):
        if not hasattr(self, "_env"):
            self._init_state()
            return
        new_phase = self._config.get("phase", "none")
        self._phase_pending = new_phase if new_phase != self._phase else None

    def _refresh_bg_render_state(self):
        # One colour, no background: whatever background a colour set writes
        # (42 of his sets carry a Singles background) never paints under the
        # pulse. Kept as the base computes it, then switched off.
        super()._refresh_bg_render_state()
        self.bg_color_use = False

    # ── audio path (audio thread, under self.lock) ───────────────────────

    def audio_data_updated(self, data):
        x = self._hit_signal(data)
        rate = AUDIO_RATE_DEFAULT
        try:
            rate = float(data._config.get("sample_rate", AUDIO_RATE_DEFAULT))
        except Exception:
            pass
        if self._config["beat_ms"] <= 0:
            self._live_bpm = self._read_live_bpm(data)
        self.ingest_signal(x, 1.0 / max(1.0, rate))

    def _hit_signal(self, data):
        try:
            lows = float(np.max(data.lows_power(filtered=False)))
        except Exception:
            lows = 0.0
        if not math.isfinite(lows):
            lows = 0.0
        if self._config["hit_source"] == "bass only":
            return lows
        try:
            mel = self.melbank(filtered=False)
            mean = float(np.mean(mel)) if len(mel) else 0.0
        except (AttributeError, TypeError, IndexError):
            mean = 0.0  # a source with no melbank (headless synthetic audio)
        if not math.isfinite(mean):
            mean = 0.0
        return lows + 2.0 * mean

    @staticmethod
    def _read_live_bpm(data):
        try:
            data.bpm_beat_now()  # feeds the shared tempo tracker this frame
            return float(data._tempo.get_bpm())
        except Exception:
            return 0.0

    def ingest_signal(self, x, dt=1.0 / AUDIO_RATE_DEFAULT):
        """One audio frame of the hit signal. The audio callback calls this
        with the live signal; offline harnesses call it with a recorded one.
        CALLER HOLDS self.lock (or owns the effect single-threaded)."""
        x = float(x) if math.isfinite(x) else 0.0
        self.last_signal = x
        self._audio_t += dt
        t = self._audio_t
        if not self._primed:
            # the first frame seeds the followers: an effect switched on
            # mid-song must not read the music it walked into as one hit
            self._primed = True
            self._slow = self._prev = x
            return
        a = SLOW_RISE_ALPHA if x > self._slow else SLOW_FALL_ALPHA
        self._slow += (x - self._slow) * _per_frame(a, dt)
        rise = x - self._prev
        over = x - self._slow
        self._peak = max(
            self._peak * math.exp(-dt / PEAK_MEMORY_S), over, PEAK_FLOOR
        )
        pk = self._peak
        if (
            over > self._config["hit_sensitivity"] * pk
            and rise > RISE_MIN_FRAC * pk
            and (t - self._last_hit) >= REFRACTORY_S
        ):
            strength = min(1.0, over / pk)
            sharp = min(1.0, rise / (SHARP_REF * pk))
            self._last_hit = t
            self._start_hit(strength, sharp)
        elif self._attacking and rise > 0 and over > 0:
            # the hit is still growing: let the peak follow it (budget-capped)
            grown = min(1.0, over / pk) ** PEAK_EXP
            new_target = min(grown, self._hit_cap)
            if new_target > self._target:
                # same deadline, higher peak: the rise time never stretches
                self._target = new_target
                self._attack_v = (new_target - self._env) / max(
                    self._attack_left, 1e-6)
                self._hit_entry[1] = self._swing(new_target)
        self._prev = x

    def _start_hit(self, strength, sharp):
        rise_ms = _lerp(
            self._config["rise_soft_ms"],
            self._config["rise_sharp_ms"],
            sharp * math.sqrt(strength),
        )
        want = max(self._env, strength ** PEAK_EXP)
        cap = self._budget_cap()
        target = max(self._env, min(want, cap))
        self._hit_cap = max(cap, self._env)
        self._target = target
        rise_s = max(0.0, rise_ms) / 1000.0
        delta = target - self._env
        self._attacking = delta > 1e-9
        self._attack_left = rise_s
        self._attack_v = (delta / rise_s) if rise_s > 0 else math.inf
        self._hit_entry = [self._audio_t, self._swing(target)]
        self._flash_window.append(self._hit_entry)
        self.hits.append(
            (self._audio_t, strength, sharp, rise_ms, want, target)
        )

    # ── flash-rate budget ────────────────────────────────────────────────

    def _budget_left(self):
        win = self._flash_window
        cutoff = self._audio_t - FLASH_WINDOW_S
        while win and win[0][0] <= cutoff:
            win.popleft()
        used = sum(w[1] for w in win)
        return max(0.0, self._config["max_flash_rate"] - used)

    def _swing(self, env):
        """Rise in delivered light (0..1) if the envelope went to `env` now."""
        g = self._config["gamma"]
        return max(0.0, self._compose(env)[0] ** g - self.level ** g)

    def _budget_cap(self):
        """The largest envelope value this hit may reach without the last
        second's rises summing past max_flash_rate."""
        budget = self._budget_left()
        if self._swing(1.0) <= budget:
            return 1.0
        lo, hi = self._env, 1.0
        if self._swing(lo) > budget:
            return lo
        for _ in range(24):
            mid = 0.5 * (lo + hi)
            if self._swing(mid) <= budget:
                lo = mid
            else:
                hi = mid
        return lo

    # ── tempo / energy ───────────────────────────────────────────────────

    def beat_s(self):
        bm = self._config["beat_ms"]
        if bm > 0:
            return min(2.0, max(0.2, bm / 1000.0))
        lo, hi = LIVE_BPM_RANGE
        if lo <= self._live_bpm <= hi:
            return 60.0 / self._live_bpm
        return DEFAULT_BEAT_S

    def _rest_and_depth(self):
        e = min(1.0, max(0.0, self._energy_live))
        cfg = self._config
        rest = _lerp(cfg["rest_calm"], cfg["rest_intense"], e)
        depth = _lerp(cfg["depth_calm"], cfg["depth_intense"], e**DEPTH_EXP)
        return rest, depth

    def _pulse(self, env, depth):
        p = depth * env
        if env > MIN_PULSE_ENV:
            p = max(p, self._config["min_pulse"] * min(1.0, env * 3.0))
        return p

    # ── level ────────────────────────────────────────────────────────────

    def _progress(self):
        p = self._config.get("phase_progress", 0.0)
        return min(1.0, max(0.0, float(p)))

    def _compose(self, env):
        """Eye-scale level for envelope `env` under the CURRENT energy, phase,
        burst and blend state. Pure (mutates nothing): the flash budget asks
        it about hypothetical envelopes. Returns (level, rest)."""
        rest, depth = self._rest_and_depth()
        floor = rest
        ph = self._phase
        if ph == "charge":
            prog = self._progress()
            rest = _lerp(floor, self._config["charge_top"], _smooth(prog))
            d2 = max(
                CHARGE_MIN_DEPTH,
                min(depth + CHARGE_DEPTH_ADD * prog, 1.0 - rest),
            )
            level = rest + env * d2
        elif ph == "lull":
            keep = 1.0 - _smooth(self._progress())
            level = (self._lull_from + self._pulse(env, depth)) * keep
            rest = self._lull_from * keep
        else:
            level = floor + self._pulse(env, depth)
        if self._burst > 0.0:
            level = max(
                level, floor + (self._config["drop_burst"] - floor) * self._burst
            )
        if self._blend_from is not None:
            s = _smooth(self._blend_t / EXIT_BLEND_S)
            level = _lerp(self._blend_from, level, s)
        return min(1.0, max(0.0, level)), rest

    # ── phases ───────────────────────────────────────────────────────────

    def _self_reset_phase(self):
        self._apply_config(
            {"phase": "none", "phase_progress": 0.0},
            validate=False,
            fire_event=False,
        )

    def _leave_phase_without_drop(self):
        self._blend_from = self.level
        self._blend_t = 0.0

    def _enter_phase(self, phase):
        old = self._phase
        self._phase = phase
        self._phase_t = 0.0
        self._phase_done_t = None
        if phase == "drop":
            self._blend_from = None
            g = self._config["gamma"]
            self._burst = 1.0
            # never shrunk, but spent: hits right after a drop are
            rise = max(0.0, self._config["drop_burst"] ** g - self.level**g)
            self._flash_window.append([self._audio_t, rise])
            return
        if phase == "lull":
            # fade from where the light actually rests now (mid-ease: from
            # where the ease has got to)
            if self._blend_from is not None:
                self._lull_from = self.level
                self._blend_from = None
            else:
                self._lull_from = self._rest
            return
        if old in ("charge", "lull"):
            self._leave_phase_without_drop()

    def _phase_step(self, dt):
        pend = self._phase_pending
        if pend is not None:
            self._phase_pending = None
            if pend != self._phase:
                self._enter_phase(pend)
        if self._phase == "none":
            return
        self._phase_t += dt
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self._progress(), self._phase_t, self._phase_done_t
        )
        if due:
            _LOGGER.info(
                "pulse: %s watchdog release after %.1fs",
                self._phase,
                self._phase_t,
            )
            self._leave_phase_without_drop()
            self._phase = "none"
            self._self_reset_phase()
            return
        if self._phase == "drop" and self._burst < BURST_DONE:
            self._phase = "none"
            self._self_reset_phase()

    # ── render ───────────────────────────────────────────────────────────

    def _advance_envelope(self, dt):
        if self._attacking:
            self._attack_left -= dt
            self._env = min(self._target, self._env + self._attack_v * dt)
            if self._env >= self._target - 1e-9 or self._attack_left <= 1e-9:
                self._env = self._target
                self._attacking = False
            return
        fade_beats = _lerp(
            self._config["fade_beats_calm"],
            self._config["fade_beats_intense"],
            min(1.0, max(0.0, self._energy_live)),
        )
        if self._phase == "charge":
            fade_beats *= _lerp(1.0, CHARGE_FADE_X, self._progress())
        tau = max(1e-3, fade_beats * self.beat_s() / LN10)
        self._env *= math.exp(-dt / tau)

    def colour(self):
        """The light's colour: the gradient's first colour (0..255 RGB)."""
        return np.asarray(self.get_gradient_color(0.0), dtype=float)

    def render(self):
        dt = min(max(float(self.passed), 0.0), DT_MAX)
        target_e = float(self._config["energy"])
        self._energy_live += (target_e - self._energy_live) * (
            1.0 - math.exp(-dt / ENERGY_SLEW_S)
        )
        self._phase_step(dt)
        self._advance_envelope(dt)
        level, self._rest = self._compose(self._env)
        white = self._config["drop_white"] * self._burst**2
        if self._burst > 0.0:
            tau = self._config["drop_settle_beats"] * self.beat_s() / LN10
            self._burst *= math.exp(-dt / max(1e-3, tau))
            if self._burst < BURST_DONE:
                self._burst = 0.0
        if self._blend_from is not None:
            self._blend_t += dt
            if self._blend_t >= EXIT_BLEND_S:
                self._blend_from = None
        self.level = level
        self.white = white
        lin = level ** self._config["gamma"]
        rgb = (self.colour() * (1.0 - white) + 255.0 * white) * lin
        self.pixels[:] = rgb
