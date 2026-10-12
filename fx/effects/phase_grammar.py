"""THE PHASE GRAMMAR — the drop's SHOCKWAVE and the lull's BREATH-HOLD.

Plan: /home/javi/fleet-spotfx/data/transitions-drop-plan/report.md (rev 3),
phase 1, the Admiral's rulings on it (2026-10-11):

- "have the shockwave originate from the permieter of the eye, not the
  center of the screen. Also, don't do the shockwave for fireworks."
- "i don't want to raise the white in the charge, or on the drop. What I
  mean by increasing/decreasing brightness in this case is adding more
  color, increasing the brightness of the colors, and having more baseline
  effects" — SET COLOURS ONLY, NEVER WHITE.
- Q2: "a 0.4 s true black just before the drop, as a setting".

It is lull_dark.py's and lull_handoff.py's sibling and follows their rules:
pure curves of (time in phase, the told keys, intensity) live here; an
effect opts in with a class attribute and one call; anything SpotFX knows
that the effect cannot (the lull's real length, the drop's intensity, the
room's breath-hold setting) rides the phase ARM WRITE
(spectra scene_response._drive_phase), never the effect-parameter registry.

THE SHOCKWAVE (drop)
====================

A shared overlay painted by the base `Twod.render` AFTER the effect's own
draw(), under which the effect's own payoff still runs. Four layers, every
one in the colour set's own colours and every one composed by MAX — never a
sum — so overlapping colours can never saturate toward white:

1. RIM BLOOM (0 .. `drop_bloom_ms`): the eye's perimeter lights in the
   set's brightest stop at full, then fades. Not a whole-panel flash.
2. ONE WAVEFRONT: born ON the rim, a sharp leading edge with a short
   trailing wake (`drop_wake`) running outward at `drop_ring_speed`
   (normalized panel units / s — 1.0 is the panel centre to its edge
   midpoint) and on past the hex edge. Its colour is the set by angle,
   leaned toward the set's brightest stop by `drop_color_lean` (the lean
   moves the SAMPLE POSITION along the gradient toward that stop, so every
   colour drawn is a real point of the set, never an RGB mix). Ahead of it
   the effect's own frame is held dark by `drop_reveal` and revealed as the
   front passes; inside the rim the eye is never hidden.
3. DEBRIS: `drop_debris_n` pieces (x the drop's intensity scale x the
   member's own SHOCK_DEBRIS_BOOST), born on the rim and carried just
   inside the front at `drop_debris_speed` x the ring speed, each wearing
   the set's colour at its own angle (the whole set). The COUNT rises with
   intensity, never the brightness. After DEBRIS_TURN_S each piece meets its
   member's fate (SHOCK_DEBRIS_FATE): "return" curves it back to the rim
   (Black Hole's infall, Orbits' ring, the Fish's home ring), "fade" burns
   it out as a flame lick (Sauron, Eye).
4. THE SPLASH ON THE WALL: the crystal's outermost real cells light only
   where the front has struck them, in the set's colour at that angle, and
   fade over `drop_afterglow_beats` (x BEAT_S; 0 = none).

"The eye" is each member's own centre form, named by `shock_rim()`:
(cx, cy, rx, ry) in the effect's render pixels — Black Hole's horizon,
Orbits' tether ring, the Fish's home ring (ring radius x the projection),
Sauron/Eye's iris rim (a circle in the eye's own isotropic pixels).

INTENSITY: the drop arm tells every member the fire's intensity
(`drop_intensity`, lull_handoff.DROP_KEY — fx.device_model.
DROP_INTENSITY_EFFECTS is widened to every member). `shock_scale` turns it
into one multiple with lull_handoff.drop_scale (`drop_shock_scale_min` at
intensity 0, exactly 1.0 at the automatic ceiling 0.75, DROP_SCALE_MAX on a
marked track at 1.0); it scales the debris count and how long the front
and its wake stay lit. Not told: 1.0 — the shipped defaults.

HOW AN EFFECT OPTS IN (the Twod subclass):
  1. `DROP_SHOCK = True`, a SHOCK_DEBRIS_FATE ("return"/"fade") and
     optionally SHOCK_DEBRIS_BOOST (Black Hole's is the boost — the plan's
     "Black Hole debris boost");
  2. splice `**shock_schema_fields()` and `**breath_schema_fields()` and
     lull_handoff.drop_schema_fields() into CONFIG_SCHEMA, and the
     BREATH_KEYS + DROP_KEY into ADVANCED_KEYS;
  3. implement `shock_rim()` and call `self._shock_begin()` at the moment
     its own drop payoff fires (never on a silent watchdog release);
  4. add its registry name to fx.device_model.DROP_SHOCK_EFFECTS (which is
     what makes SpotFX push the breath and drop keys) and register the
     SHOCK_PARAMS in config/effect_params.json so Sonic reaches them.
NEVER FIREWORKS (his word): it keeps its own drop.

WHETHER IT MAY PAINT AT ALL (2026-10-12, the Admiral: "Shockwave should be
a setting that can be toggled per scene, as well as globally, as well as a
global setting for minimum energy before it is allowed to fire. As i
understand it, it is an overlay, so it should easily be able to be turned
off"). It IS an overlay: nothing here touches the effect's own drop (Black
Hole's burst, the Fish's rush, Orbits' ejecta, the Eye's lids all run in
the effect's own draw(), before this module is reached), so switching it
off is "never build the painter". Three switches decide, all SpotFX's
(spectra scene_response._drive_phase, `shock_allowed` below is the one
rule): the room's `drop_shock_enabled`, the showing scene's own
`drop_shock_enabled`, and the room's `drop_shock_min_energy` against the
TOP BAR'S Energy at the drop (bridge.intensity(), the same number the drop
floor reads — an unknown energy is never gated). The verdict rides every
member's DROP ARM as `drop_shock_on` (SHOCK_ON_KEY, every drop, every
member, so an earlier "off" is never left standing); untold (the LedFX UI,
a test with no SpotFX) it reads True — the shipped behaviour. When it is
False the drop's frame is the effect's own, byte for byte: no bloom, no
wavefront, no debris, no wall splash, and no reveal hold-back either (the
reveal is the overlay's, not the effect's). The per-effect `drop_shock`
strength is a SEPARATE, effect-level knob and stays as it is. The strips'
own drop shockwave (fx/effects/strip_phase.py) is not governed by this.

THE BREATH-HOLD (lull)
======================

A short TRUE BLACK right before the drop mark: SpotFX tells every member's
lull arm when the breath starts (`lull_breath_at_s`, seconds on the effect's
own phase clock) and how long it is (`lull_breath_s`); the base render
multiplies the frame to black for that window. The length is the room's
`lull_breath_hold_s` (default 0.4 s, Sonic-editable, 0 disables) and is
always INSIDE the lull's dark rule (`lull_dark.dark_hold_s`: half the lull,
never more than `lull_dark_max_s`), so it can never be longer than the dark
the room already allows — on Black Hole, whose lull is already dark there,
it changes nothing. A gap SpotFX cannot know (no partner trigger) tells 0:
there is no mark to breathe before. If the drop never comes, the panel
comes back BREATH_OVERRUN_S after the breath should have ended rather than
staying black until the orphan watchdog.
"""

from __future__ import annotations

from typing import Callable, Mapping, Optional

import numpy as np
import voluptuous as vol

from fx.effects import lull_dark, lull_handoff

# ── the breath-hold ─────────────────────────────────────────────────────────

BREATH_AT_KEY = "lull_breath_at_s"
BREATH_KEY = "lull_breath_s"
BREATH_KEYS = (BREATH_AT_KEY, BREATH_KEY)

DEFAULT_BREATH_S = 0.4
# the panel eases into the black over this long, BEFORE the breath starts,
# so the true black is the whole breath and nothing pops
BREATH_FADE_S = 0.08
# a drop that never arrives: the lull picture returns this long after the
# breath was due to end (a seek, a lost trigger) instead of holding black
BREATH_OVERRUN_S = 0.5


def breath_s(lull_s: float, setting_s: float, max_dark_s: float) -> float:
    """The breath's length: the room's setting, never longer than the lull's
    own dark hold (half the lull, capped at `max_dark_s`)."""
    hold = lull_dark.dark_hold_s(lull_s, max_dark_s)
    return max(0.0, min(max(0.0, float(setting_s)), hold))


def breath_keys_for(lull_s: Optional[float], setting_s: float,
                    max_dark_s: float) -> dict:
    """The two keys SpotFX pushes on every member's lull arm. `lull_s` is the
    real gap to the drop, or None when it is unknowable (then nothing to
    breathe before: 0)."""
    if lull_s is None or lull_s <= 0.0:
        return {BREATH_AT_KEY: 0.0, BREATH_KEY: 0.0}
    b = breath_s(lull_s, setting_s, max_dark_s)
    return {BREATH_AT_KEY: max(0.0, float(lull_s) - b), BREATH_KEY: b}


def breath_schema_fields() -> dict:
    return {
        vol.Optional(
            BREATH_AT_KEY,
            description="Lull: seconds from the lull's start to the "
                        "breath-hold black (driven by SpotFX)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Optional(
            BREATH_KEY,
            description="Lull: the breath-hold's length in seconds (driven "
                        "by SpotFX; 0 = none)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
    }


def breath_gain(config: Mapping, phase_t: float) -> float:
    """How much of the lull's own picture shows at `phase_t` seconds into
    the lull: 1.0 = untouched, 0.0 = the breath's true black."""
    try:
        b = float(config.get(BREATH_KEY, 0.0) or 0.0)
        at = float(config.get(BREATH_AT_KEY, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 1.0
    if b <= 0.0:
        return 1.0
    t = float(phase_t)
    if t >= at + b + BREATH_OVERRUN_S:
        return 1.0
    if t >= at:
        return 0.0
    fade_from = at - BREATH_FADE_S
    if t <= fade_from:
        return 1.0
    return float((at - t) / BREATH_FADE_S)


# ── the Shockwave's settings (registered, Sonic-reachable) ─────────────────

# (key, default, min, max, label, note) — the plan's table, his to tune
SHOCK_PARAMS = (
    ("drop_shock", 1.0, 0.0, 1.0, "Drop Shockwave",
     "How strongly the drop's Shockwave is painted over this effect's own "
     "drop: the rim bloom, the wavefront, the debris and the wall splash. "
     "0 turns it off; always in the colour set's own colours."),
    ("drop_bloom_ms", 190.0, 0.0, 400.0, "Drop Bloom (ms)",
     "How long the eye's rim blooms in the set's brightest colour on the "
     "drop mark. 0 = no bloom."),
    ("drop_color_lean", 0.45, 0.0, 1.0, "Drop Colour Lean",
     "How far the wavefront leans toward the set's brightest colour "
     "(0 = the set by angle, 1 = all the brightest colour). Never white."),
    ("drop_ring_speed", 1.15, 0.6, 3.0, "Drop Wave Speed",
     "How fast the wavefront runs out from the eye's rim, in panels per "
     "second (1 = the panel's centre to its edge)."),
    ("drop_ring_width", 0.05, 0.03, 0.2, "Drop Wave Width",
     "How thick the wavefront's sharp leading edge is."),
    ("drop_wake", 0.13, 0.0, 0.4, "Drop Wave Wake",
     "How long a glowing tail the wavefront trails behind it."),
    ("drop_debris_n", 45.0, 0.0, 150.0, "Drop Debris",
     "Debris pieces flung from the rim at full intensity; fewer on a "
     "quieter drop. The count rises with the music, never the brightness."),
    ("drop_debris_speed", 0.85, 0.5, 1.5, "Drop Debris Speed",
     "Debris speed as a multiple of the wave's speed (below 1 keeps it just "
     "inside the front)."),
    ("drop_afterglow_beats", 1.5, 0.0, 4.0, "Drop Wall Splash (beats)",
     "How long the crystal's edge glows where the wave strikes it. 0 = no "
     "splash."),
    ("drop_reveal", 0.75, 0.0, 1.0, "Drop Reveal",
     "How dark this effect's own drop is held ahead of the wavefront before "
     "the wave passes and reveals it (0 = never held)."),
    ("drop_shock_scale_min", 0.55, 0.1, 1.0, "Drop Quiet Scale",
     "How much of the Shockwave a quiet drop gets (intensity 0), as a "
     "fraction of the full one at the automatic ceiling."),
)
SHOCK_KEYS = tuple(p[0] for p in SHOCK_PARAMS)
SHOCK_DEFAULTS = {p[0]: p[1] for p in SHOCK_PARAMS}
SHOCK_HELP_TOPIC = "drop-shockwave"

# ── whether a drop may paint the Shockwave at all (module docstring) ──────

# Told on every member's drop arm; never in the effect-parameter registry
# (like the phase keys) — it is SpotFX's verdict, not a per-effect setting.
SHOCK_ON_KEY = "drop_shock_on"
DEFAULT_SHOCK_MIN_ENERGY = 0.7

# the verdict's reasons, named in the drop's record
SHOCK_ALLOWED = "allowed"
SHOCK_ROOM_OFF = "room_off"
SHOCK_SCENE_OFF = "scene_off"
SHOCK_BELOW_ENERGY = "below_energy"
SHOCK_ENERGY_UNKNOWN = "energy_unknown"   # allowed: an unknown is never gated


def shock_allowed(room_on: bool, scene_on: bool, energy: Optional[float],
                  min_energy: float) -> tuple[bool, str]:
    """THE rule: may this drop paint the Shockwave, and why. The room's
    switch wins, then the scene's, then the energy floor (`energy >=
    min_energy`; a floor of 0 never gates; the loudest section of a song
    reads exactly 1.0, so even a floor of 1.0 lets that section through —
    the room switch is what turns it off). An energy that cannot be read
    is never gated (the drop floor's own rule)."""
    if not room_on:
        return False, SHOCK_ROOM_OFF
    if not scene_on:
        return False, SHOCK_SCENE_OFF
    if energy is None:
        return True, SHOCK_ENERGY_UNKNOWN
    try:
        floor = float(min_energy)
    except (TypeError, ValueError):
        floor = DEFAULT_SHOCK_MIN_ENERGY
    if float(energy) < floor:
        return False, SHOCK_BELOW_ENERGY
    return True, SHOCK_ALLOWED


def shock_on_schema_fields() -> dict:
    return {
        vol.Optional(
            SHOCK_ON_KEY,
            description="Drop: whether this drop may paint the Shockwave "
                        "(driven by SpotFX: the room's and the scene's "
                        "switches and the energy floor)",
            default=True,
        ): bool,
    }


def shock_on(config: Mapping) -> bool:
    """The told verdict; True when not told."""
    return config.get(SHOCK_ON_KEY, True) is not False


def shock_schema_fields() -> dict:
    out = {}
    for key, default, lo, hi, label, note in SHOCK_PARAMS:
        if key == "drop_debris_n":
            out[vol.Optional(key, description=note, default=int(default))] = (
                vol.All(vol.Coerce(int), vol.Range(min=int(lo), max=int(hi))))
        else:
            out[vol.Optional(key, description=note, default=default)] = (
                vol.All(vol.Coerce(float), vol.Range(min=lo, max=hi)))
    return out


def registry_params() -> dict:
    """The SHOCK_PARAMS as config/effect_params.json `params` entries (the
    one place their registry shape is derived from — scripts and tests
    compare the stored registry against this)."""
    out = {}
    for key, default, lo, hi, label, note in SHOCK_PARAMS:
        is_int = key == "drop_debris_n"
        out[key] = {
            "label": label,
            "type": "numeric",
            "smooth": not is_int,
            "min": int(lo) if is_int else lo,
            "max": int(hi) if is_int else hi,
            "aspect": "shape",
            "note": note,
            "help_topic": SHOCK_HELP_TOPIC,
            "default": int(default) if is_int else default,
        }
    return out


# ── pure curves ─────────────────────────────────────────────────────────────

# one beat for the wall splash's length (the effects are not told the tempo;
# 0.5 s is 120 bpm, his songs' middle)
BEAT_S = 0.5
FRONT_LIFE_S = 1.2       # the wavefront's own life at scale 1.0
DEBRIS_LIFE_S = 2.5
DEBRIS_TURN_S = 0.8      # when a piece meets its member's fate
DEBRIS_FADE_S = 0.6      # a "fade" piece burns out over this long
DEBRIS_SPREAD = 0.12     # +/- on each piece's own speed
DEBRIS_SWIRL = 0.35      # tangential share of a piece's launch (rad/s / unit)
DEBRIS_TRAIL_HALF_S = 0.07
DEBRIS_CAP = 150
WALL_BAND = (-0.04, 0.16)  # face-distance band of the crystal's outer cells
BLOOM_HOLD_FRAC = 0.3    # the bloom holds full for this share of its length
REVEAL_EDGE_PAD = 0.25   # the reveal ends this far past the farthest cell


def shock_scale(intensity: Optional[float], scale_min: float) -> float:
    """The drop's size multiple (module docstring); 1.0 when not told."""
    s = lull_handoff.drop_scale(intensity, scale_min)
    return 1.0 if s is None else float(s)


def bloom_alpha(t: float, bloom_s: float) -> float:
    if bloom_s <= 0.0 or t >= bloom_s or t < 0.0:
        return 0.0
    hold = BLOOM_HOLD_FRAC * bloom_s
    if t <= hold:
        return 1.0
    return float(1.0 - (t - hold) / (bloom_s - hold))


def front_alpha(t: float, scale: float) -> float:
    life = FRONT_LIFE_S * max(scale, 1e-3)
    if t < 0.0 or t >= life:
        return 0.0
    return float((1.0 - t / life) ** 0.5)


def front_profile(s: np.ndarray, front: float, width: float,
                  wake: float) -> np.ndarray:
    """The wavefront's shape across `s` (distance outside the rim): a sharp
    leading edge at `front` and an exponential wake behind it."""
    d = s - front
    w = max(width, 1e-3)
    core = np.exp(-((d / w) ** 2))
    if wake > 0.0:
        tail = np.where(d < 0.0, np.exp(np.minimum(d, 0.0) / wake), 0.0)
        core = np.maximum(core, 0.6 * tail)
    # nothing behind the rim's own edge belongs to the front
    return np.where(s >= 0.0, core, 0.0)


def ellipse_radius(theta: np.ndarray, a: float, b: float) -> np.ndarray:
    """An axis-aligned ellipse's radius along `theta`."""
    a = max(float(a), 1e-4)
    b = max(float(b), 1e-4)
    c = np.cos(theta)
    s = np.sin(theta)
    return (a * b) / np.sqrt((b * c) ** 2 + (a * s) ** 2)


def lean_positions(pos: np.ndarray, bright_pos: float,
                   lean: float) -> np.ndarray:
    """Move gradient sample positions toward the brightest stop's position
    along the shortest way round the (cyclic) colour set — every result is a
    real point of the set."""
    d = (bright_pos - pos + 0.5) % 1.0 - 0.5
    return (pos + float(np.clip(lean, 0.0, 1.0)) * d) % 1.0


def brightest_position(sample: Callable[[np.ndarray], np.ndarray],
                       n: int = 64) -> float:
    """Where along the gradient its brightest colour sits (by the brightest
    channel, then by the channel sum)."""
    pos = np.linspace(0.0, 1.0, n, endpoint=False)
    rgb = np.asarray(sample(pos), dtype=np.float32).reshape(-1, 3)
    key = rgb.max(axis=1) * 4.0 + rgb.sum(axis=1) / 3.0
    return float(pos[int(np.argmax(key))])


# ── the panel's static fields ───────────────────────────────────────────────

class PanelField:
    """Per-render-size static fields: panel-normalized coordinates (r = 1 at
    the edge midpoints, the crystal-hex-grid skill's convention) and the
    crystal's hex face distance (positive inside). Cached per size."""

    def __init__(self, width: int, height: int):
        from fx.effects import blackhole as _bh   # lazy: blackhole imports twod
        self.width = int(width)
        self.height = int(height)
        self.hx = max((self.width - 1) / 2.0, 1e-6)
        self.hy = max((self.height - 1) / 2.0, 1e-6)
        yi, xi = np.indices((self.height, self.width))
        self.x = xi.astype(np.float32)
        self.y = yi.astype(np.float32)
        gx = (self.x - self.hx) / self.hx
        gy = (self.y - self.hy) / self.hy
        face = np.full_like(gx, np.inf)
        for nx, ny, dd in zip(_bh._HEX_FACE_NX, _bh._HEX_FACE_NY,
                              _bh._HEX_FACE_D):
            face = np.minimum(face, dd - (nx * gx + ny * gy))
        self.face = face.astype(np.float32)
        self.wall = (face >= WALL_BAND[0]) & (face <= WALL_BAND[1])


_FIELDS: dict = {}


def panel_field(width: int, height: int) -> PanelField:
    key = (int(width), int(height))
    f = _FIELDS.get(key)
    if f is None:
        f = _FIELDS[key] = PanelField(*key)
    return f


# ── the painter ─────────────────────────────────────────────────────────────

class Shockwave:
    """One drop's Shockwave on one effect instance (module docstring).
    `rim` is (cx, cy, rx, ry) in render pixels; `sample(positions)` the
    effect's own gradient (N x 3, 0-255); `config` its settings."""

    def __init__(self, field: PanelField, rim, sample, config: Mapping,
                 intensity: Optional[float], fate: str = "return",
                 boost: float = 1.0, rng=None):
        self.field = field
        self.fate = fate if fate in ("return", "fade") else "return"
        self.t = 0.0
        cfg = {**SHOCK_DEFAULTS, **{k: config[k] for k in SHOCK_KEYS
                                    if k in config}}
        self.strength = float(np.clip(cfg["drop_shock"], 0.0, 1.0))
        self.bloom_s = float(cfg["drop_bloom_ms"]) / 1000.0
        self.lean = float(cfg["drop_color_lean"])
        self.speed = max(float(cfg["drop_ring_speed"]), 1e-3)
        self.width = float(cfg["drop_ring_width"])
        self.wake = float(cfg["drop_wake"])
        self.debris_speed = float(cfg["drop_debris_speed"])
        self.afterglow_s = float(cfg["drop_afterglow_beats"]) * BEAT_S
        self.reveal = float(np.clip(cfg["drop_reveal"], 0.0, 1.0))
        self.scale = shock_scale(intensity, float(cfg["drop_shock_scale_min"]))
        self.rng = rng if rng is not None else np.random.default_rng()

        cx, cy, rx, ry = (float(v) for v in rim)
        self.cx, self.cy = cx, cy
        self.a = max(rx / field.hx, 1e-3)
        self.b = max(ry / field.hy, 1e-3)
        dx = (field.x - cx) / field.hx
        dy = (field.y - cy) / field.hy
        self.theta = np.arctan2(dy, dx).astype(np.float32)
        self.s = (np.hypot(dx, dy)
                  - ellipse_radius(self.theta, self.a, self.b)).astype(
                      np.float32)
        self.s_max = float(self.s[field.face >= WALL_BAND[0]].max(
            initial=0.0))

        # colours: the set by angle, leaned toward its brightest stop
        self.sample = sample
        self.bright_pos = brightest_position(sample)
        bright = np.asarray(sample(np.array([self.bright_pos])),
                            dtype=np.float32).reshape(3)
        self.bright_rgb = bright
        ang_pos = ((self.theta / (2.0 * np.pi)) % 1.0).ravel()
        self.angle_rgb = np.asarray(sample(ang_pos), dtype=np.float32
                                    ).reshape(field.height, field.width, 3)
        self.front_rgb = np.asarray(
            sample(lean_positions(ang_pos, self.bright_pos, self.lean)),
            dtype=np.float32).reshape(field.height, field.width, 3)

        # the wall: each outer cell's moment of impact
        self.wall = field.wall & (self.s > 0.0)
        self.wall_hit_t = np.where(self.wall, self.s / self.speed, np.inf
                                   ).astype(np.float32)

        # debris: born on the rim, the whole set by angle
        n = int(round(float(cfg["drop_debris_n"]) * self.scale
                      * max(float(boost), 0.0) * self.strength))
        n = max(0, min(n, DEBRIS_CAP))
        th = self.rng.uniform(0.0, 2.0 * np.pi, n).astype(np.float32)
        r0 = ellipse_radius(th, self.a, self.b).astype(np.float32)
        self.d_th = th
        self.d_r = r0.copy()
        self.d_r0 = r0
        v = (self.speed * self.debris_speed
             * (1.0 + self.rng.uniform(-DEBRIS_SPREAD, DEBRIS_SPREAD, n)))
        self.d_vr = v.astype(np.float32)
        self.d_om = (self.rng.uniform(-1.0, 1.0, n) * DEBRIS_SWIRL
                     ).astype(np.float32)
        self.d_alive = np.ones(n, dtype=bool)
        self.d_bright = np.ones(n, dtype=np.float32)
        self.d_rgb = np.asarray(
            sample((th / (2.0 * np.pi)) % 1.0), dtype=np.float32
        ).reshape(n, 3) if n else np.zeros((0, 3), np.float32)
        self.d_buf = np.zeros((field.height, field.width, 3), np.float32)
        self.life = max(FRONT_LIFE_S * self.scale, self.bloom_s,
                        DEBRIS_LIFE_S if n else 0.0,
                        (float(self.wall_hit_t[self.wall].max(initial=0.0))
                         + self.afterglow_s) if self.afterglow_s > 0 else 0.0)

    @property
    def done(self) -> bool:
        return self.strength <= 0.0 or self.t > self.life

    # ── per frame ──
    def step(self, dt: float) -> None:
        dt = float(min(max(dt, 0.0), 0.1))
        self.t += dt
        self._step_debris(dt)

    def _step_debris(self, dt: float) -> None:
        n = self.d_th.size
        if n == 0 or dt <= 0.0:
            self.d_buf *= 0.0
            return
        a = self.d_alive
        t = self.t
        if t >= DEBRIS_TURN_S:
            if self.fate == "return":
                # curve back to the rim: the outward speed bleeds off and
                # turns inward, so the piece arcs home and dies there
                self.d_vr[a] -= dt * self.speed * 2.2
                home = a & (self.d_vr < 0.0) & (self.d_r <= self.d_r0)
                self.d_alive &= ~home
            else:
                # a flame lick: slows and burns out
                self.d_vr[a] *= np.float32(0.5 ** (dt / 0.25))
                self.d_bright[a] = np.clip(
                    1.0 - (t - DEBRIS_TURN_S) / DEBRIS_FADE_S, 0.0, 1.0)
        self.d_r[a] += self.d_vr[a] * dt
        self.d_th[a] += self.d_om[a] * dt
        if t >= DEBRIS_LIFE_S:
            self.d_alive[:] = False
        self.d_alive &= self.d_bright > 0.0
        self.d_buf *= np.float32(0.5 ** (dt / DEBRIS_TRAIL_HALF_S))
        a = self.d_alive
        if not a.any():
            return
        f = self.field
        px = self.cx + self.d_r[a] * np.cos(self.d_th[a]) * f.hx
        py = self.cy + self.d_r[a] * np.sin(self.d_th[a]) * f.hy
        rgb = self.d_rgb[a] * self.d_bright[a][:, None]
        # a 2-cell-wide dot so it survives the crystal's row parity
        for ox, oy, w in ((0, 0, 1.0), (1, 0, 0.8), (-1, 0, 0.8),
                          (0, 1, 0.55), (0, -1, 0.55)):
            xi = np.round(px).astype(np.int32) + ox
            yi = np.round(py).astype(np.int32) + oy
            ok = (xi >= 0) & (xi < f.width) & (yi >= 0) & (yi < f.height)
            if not ok.any():
                continue
            cur = self.d_buf[yi[ok], xi[ok]]
            np.maximum(cur, rgb[ok] * w, out=cur)
            self.d_buf[yi[ok], xi[ok]] = cur

    def overlay(self) -> np.ndarray:
        """The four layers, max-composed (H x W x 3, 0-255)."""
        f = self.field
        t = self.t
        out = np.zeros((f.height, f.width, 3), np.float32)
        ba = bloom_alpha(t, self.bloom_s)
        if ba > 0.0:
            w = max(self.width * 1.5, 0.06)
            band = np.exp(-((self.s / w) ** 2)) * ba
            np.maximum(out, band[..., None] * self.bright_rgb[None, None, :],
                       out=out)
        fa = front_alpha(t, self.scale)
        if fa > 0.0:
            prof = front_profile(self.s, self.speed * t, self.width,
                                 self.wake) * fa
            np.maximum(out, prof[..., None] * self.front_rgb, out=out)
        if self.afterglow_s > 0.0:
            since = t - self.wall_hit_t
            g = np.where(self.wall & (since >= 0.0),
                         np.clip(1.0 - since / self.afterglow_s, 0.0, 1.0),
                         0.0)
            if g.any():
                np.maximum(out, g[..., None] * self.angle_rgb, out=out)
        np.maximum(out, self.d_buf, out=out)
        return out * self.strength

    def reveal_mask(self) -> Optional[np.ndarray]:
        """The effect's own frame held dark ahead of the front (1 = shown);
        None once the front has left every cell."""
        front = self.speed * self.t
        if self.reveal <= 0.0 or front > self.s_max + REVEAL_EDGE_PAD:
            return None
        held = np.clip((self.s - front) / max(self.width, 1e-3) + 0.5,
                       0.0, 1.0)
        held = np.where(self.s > 0.0, held, 0.0)
        return (1.0 - self.reveal * self.strength * held).astype(np.float32)

    def composite(self, frame: np.ndarray) -> np.ndarray:
        """The effect's frame under the Shockwave: revealed, then max."""
        mask = self.reveal_mask()
        if mask is not None:
            frame = frame * mask[..., None]
        return np.maximum(frame, self.overlay())


def white_cells(frame: np.ndarray, threshold: float = 200.0) -> int:
    """Cells with every channel above `threshold` — the white guard's
    measure (the plan's own: 0 on every re-rendered drop frame)."""
    return int(np.count_nonzero((np.asarray(frame) > threshold).all(axis=-1)))


__all__ = [
    "BREATH_AT_KEY", "BREATH_KEY", "BREATH_KEYS", "DEFAULT_BREATH_S",
    "breath_s", "breath_keys_for", "breath_schema_fields", "breath_gain",
    "SHOCK_PARAMS", "SHOCK_KEYS", "SHOCK_DEFAULTS", "shock_schema_fields",
    "SHOCK_ON_KEY", "DEFAULT_SHOCK_MIN_ENERGY", "shock_allowed",
    "shock_on_schema_fields", "shock_on",
    "registry_params", "shock_scale", "Shockwave", "panel_field",
    "white_cells",
]
