"""THE STRIP PHASE LAYER — charge, lull and drop on every 1-D strip effect.

His ask, 2026-10-11 (the Admiral, verbatim): "add charge, lull, and drop
effects to the 1d strip effects, like 1d orbits, fireworks, and black hole,
and melt. Generally, they should increase in brightness and activity during
charge, dim and relax into black for most lulls, and big explosion of
brightness and activity on the [drop]." And, binding over everything below:
"i don't want to raise the white in the charge, or on the drop. What I mean
by increasing/decreasing brightness in this case is adding more color,
increasing the brightness of the colors, and having more baseline effects,
like more orbiting blobs, more fireworks, etc, to increase the perceived
brightness."

Plan: /home/javi/fleet-spotfx/data/strip-phase-plan/report.md (revision 3;
its phase 1 is this module, Melt and Power joining it, the flare punch and
the house-mode hold; its phase 2 is the Black Hole strip joining it — the
first member with phase choreography of its own, see step 5 below); its
phase 3 is the Orbits and Fireworks strips joining it and the three particle
strips' duplicated phase plumbing (edge detection, the orphan watchdog, the
drop's self-reset) moving in here — see THE PARTICLE STRIPS' PLUMBING
below). ONE layer, ONE line per effect to join, no SpotFX code change per
effect.

WHAT IT LISTENS TO — only keys SpotFX sends on a phase write (spectra
scene_response._drive_phase): `phase`, `phase_progress`, the lull's
dark-point timing (`lull_ramp_s`/`lull_dark_s`, fx/effects/lull_dark.py),
`drop_intensity` (fx/effects/lull_handoff.py), plus three this layer adds:
`strip_phase_strength` (the room's master, pushed on every arm write),
`flare_punch` (a self-resetting poke, the `burst_rockets` shape) and
`flare_punch_hold_s` (the punching flare's own hold). None of them is in
the effect-parameter registry: they ride only the dedicated writes.

WHAT IT PRODUCES, per frame (`StripFrame`):
  activity  a count/spawn/motion multiplier (1 = today) — "more going on";
  gain      a HUE-KEPT colour gain: a pixel's channels scale together and
            stop when its brightest channel reaches full — "brighter
            colours", never whiter;
  fill      a set-colour underfill, palette x fill x (1 - the pixel's own
            brightness): it shows where the strip is dark and gives way
            under a lit blob — "more colour";
  wave      the drop's shockwave in the SET'S COLOURS ONLY, painted OVER
            the strip (each pixel shows whichever of wave and strip is
            brighter — never the two hues added together);
  fade      the lull's fade to black (or to `lull_ember`);
  guard     the WHITE GUARD (charge and drop): no pixel may be whiter than
            the set's own colour at its hue (StripPhase._white_guard).
NO ADDED WHITE, by construction: nothing here mixes toward white, the gain
and every clip keep a pixel's hue, and the fill/wave/guard all read the
effect's own gradient — so colour jumps and rotates carry straight through.
A set that itself contains white shows its white; that is the set.

THE ORDER (StripPhase._strip_phase_stage): gain -> fill under -> wave over
-> x fade -> punch fill -> white guard.

THE CURVES (every number is a registered, Sonic-reachable param; defaults
are the plan's first guesses, pending his live tuning pass):
  charge   activity 1 -> charge_activity, gain 1 -> charge_brightness, the
           fill rising to charge_fill and shimmering faster as the build
           climbs — all on phase_progress; white guard on.
  lull     everything eases from wherever the charge left it to
           `lull_ember` (0 = black) at the room's shared DARK POINT
           (lull_dark.lull_timing — the same rule and keys the crystal's
           Black Hole, Squiggles and the Pulse singles use, so the strip
           goes dark on the same frame they do); activity relaxes to
           lull_activity and the fill fades with it, so even a sparse
           effect reads as a fade, never a cut.
  drop     begins ON its mark (the settled drop rule): a shockwave from the
           strip's centre reaching both ends in DROP_FRONT_S, sized by
           drop_shockwave x the drop's intensity, leaving a set-colour
           flood behind it (DROP_FLOOD of the wave, fading over
           DROP_FLOOD_S); gain drop_brightness settling over
           drop_brightness_settle_s, activity drop_activity settling over
           drop_settle_s; white guard on until the drop has settled. The
           drop runs on its OWN clock, so a phase reset to "none" (a track
           change's release) never cuts it short.

A FLARE IN THE LULL'S DARK PUNCHES THROUGH (his answer 5): while a lull is
running, a `flare_punch` poke opens lull_dark.punch_envelope; the fade
becomes max(the lull's fade now, punch x flare_punch_strength), activity eases back
to 1, and a faint set-colour fill (flare_punch_glow) shows only where the
lull had taken the light away. The lull's own curve keeps running
underneath, so when the envelope releases the strip is back exactly where
the lull has got to. Outside a lull a poke does nothing.

STRENGTH (`strip_phase_strength`, room setting RoomControlState.
strip_phase_strength, 0..1.5, default 1): every quantity's distance from
neutral is multiplied by it (the white guard by min(1, strength)), so 0 is
today's effect exactly — the stage does nothing and the effect's own frame
goes out byte for byte. The rollback lever.

THE ORPHAN WATCHDOG: a charge or lull whose payoff never arrives releases
itself through the shared particle_handoff.phase_release_due — an
orphaned lull must never hold a strip black.

HOW AN EFFECT JOINS (existing or future — one line, plus one set):
  1. put `StripPhase` FIRST in the effect's bases
     (`class Melt(StripPhase, AudioReactiveEffect, HSVEffect)`) — its
     CONFIG_SCHEMA (pushed keys + tunables) is merged in through the MRO;
  2. add its registry name to fx.device_model.STRIP_PHASE_EFFECTS, which is
     unioned into PHASE_EFFECTS / LULL_DARK_EFFECTS / DROP_INTENSITY_EFFECTS,
     so SpotFX starts telling it with no SpotFX change;
  3. ACTIVITY (optional): name the effect's own attributes in
     STRIP_PHASE_ACTIVITY ({"attr": weight}) — each is multiplied by
     1 + weight x (activity - 1) for one render() and put back (integers
     rounded) — the counts and density caps, not only speeds; or, for a
     clock-driven effect (Melt), multiply its own clock step by
     `self._sp_activity`.
  4. register the tunables in config/effect_params.json (registry_params()
     is the exact block) so they show on the Initial Set and Sonic reaches
     them through set_scene_entry_param.
  5. AN EFFECT WITH ITS OWN PHASE CHOREOGRAPHY (the particle strips: the
     Black Hole strip since plan phase 2, the Orbits and Fireworks strips
     since phase 3) keeps NO phase plumbing of its own — see THE PARTICLE
     STRIPS' PLUMBING below — and needs three things more:
     - its config_updated must NOT call super(): Effect._apply_config
       already calls every direct base's own hook, and a second StripPhase
       pass on a creation write turns a stale persisted phase into a false
       edge;
     - its content follows the layer's dark point, never a progress
       fraction of its own: read `_strip_phase_lull()` (the very timing the
       fade uses this frame). Its own drawn phase looks are retired in
       favour of the layer's; `_strip_phase_on_punch()` lets it answer a
       flare punch with content of its own, and `_strip_phase_punch()` says
       how far open the punch is this frame;
     - a per-effect default for a tunable (the Fireworks strip's
       `lull_ember`): splice `tunable_fields(key=default)` into its own
       CONFIG_SCHEMA (the most derived schema wins) and register
       `registry_params({key: default})`.

THE PARTICLE STRIPS' PLUMBING (plan phase 3). The edge detection, the
orphan watchdog and the drop's self-reset used to be ~70 lines copied into
each particle strip; they live here now, ONCE, on the layer's own clock:
  - `_strip_phase_enter(phase, prev, released)` is called once per edge of
    the phase key, before that frame's render() — the effect's own
    choreography starts there (a charge saves an override, a lull launches
    its rockets, a drop arms its burst). `released` is True when the edge
    is the orphan watchdog letting go of a charge or lull whose payoff
    never came (the effect decides what that looks like: a silent sweep
    back, blobs re-adding, rockets burning out);
  - STRIP_PHASE_DROP_S is the effect's own drop length: that many seconds
    into a drop the layer writes the phase key back to "none" (SpotFX
    never writes a drop's end) and calls the hook with ("none", "drop").
    The layer's own drop look runs on its own clock and is never cut short
    by it. None (Melt, Power) = the key is left alone;
  - the phase itself is `self._sp_phase` (the one phase a member has —
    no second copy of its own), seconds in it `self._sp_t`, and
    `self.phase_progress` follows the key.
tests/test_strip_phase.py's guard fails if a registered 1-D effect neither
joins nor is a named exception (fx.device_model.STRIP_PHASE_EXCEPTIONS).

WHERE IT RUNS: Effect._render calls _strip_phase_before_render /
_strip_phase_after_render around render(), and Effect.get_pixels calls
_strip_phase_stage after background and brightness, before blur — each
guarded by the class flag `_strip_phase` (False on Effect), so a
non-member effect is byte-identical. The keys this layer owns are PASSIVE
(Effect.PASSIVE_CONFIG_KEYS): a write carrying ONLY them merges into the
config without re-running the effect's own config_updated chain — a phase
ramp tweens phase_progress every frame, and re-running a gradient effect's
chain every frame resets its audio filters and snaps its gradient roll.
"""

from __future__ import annotations

import logging
import math
from typing import NamedTuple, Optional

import numpy as np
import voluptuous as vol

from fx.effects import Effect, lull_dark, lull_handoff, particle_handoff

_LOGGER = logging.getLogger(__name__)

PHASES = ("none", "charge", "lull", "drop")

STRENGTH_KEY = "strip_phase_strength"
PUNCH_KEY = "flare_punch"
PUNCH_HOLD_KEY = "flare_punch_hold_s"
DEFAULT_STRENGTH = 1.0
MAX_STRENGTH = 1.5
MAX_PUNCH = 1000

# Where the dark point sat when a lull was NOT told its timing (an older
# SpotFX, a hand-written test, a LedFX UI scrub): half the progress ramp.
LEGACY_DARK_AT = 0.5

# The drop's shockwave: the front leaves the centre on the mark and reaches
# both ends in DROP_FRONT_S; DROP_FRONT_WIDTH is its half-width as a share
# of the half-strip; it fades over DROP_FADE_S once at the ends. Behind it a
# set-colour flood at DROP_FLOOD of the wave fades over DROP_FLOOD_S.
DROP_FRONT_S = 0.28
DROP_FRONT_WIDTH = 0.12
DROP_FADE_S = 0.5
DROP_FLOOD = 0.85
DROP_FLOOD_S = 0.8
# The charge's fill carried across a charge -> drop edge (no lull between)
# fades over this, so the drop never cuts a fill off.
DROP_FILL_CARRY_S = 0.5
# An untold drop (no drop_intensity on the write) explodes at full size.
UNTOLD_DROP_INTENSITY = 1.0

# The charge fill's shimmer: depth, and its rate climbing with the build.
SHIMMER_DEPTH = 0.3
SHIMMER_HZ_START = 1.0
SHIMMER_HZ_END = 4.0
SHIMMER_SPATIAL = 3.0   # waves along the strip

# The white guard's hue resolution, and the brightest-channel floor below
# which a pixel is too dark for its hue to mean anything.
GUARD_HUE_BINS = 120   # 3 degrees
GUARD_MIN_LEVEL = 1.0

# A frame this close to neutral is not drawn at all (the effect's own
# pixels go out untouched).
NEUTRAL_EPS = 1e-6

# The tunables: (key, label, default, min, max, description). One table,
# read by the schema AND by tests/test_strip_phase.py's registry check, so
# config/effect_params.json can never drift from the schema it describes.
TUNABLES = (
    ("charge_fill", "Charge colour fill", 0.30, 0.0, 1.0,
     "Charge: set-colour fill rising under the strip at the top of the build (0 = none)"),
    ("charge_brightness", "Charge colour brightness", 1.6, 1.0, 3.0,
     "Charge: how much brighter the effect's own colours get at the top of the build (never whiter)"),
    ("charge_activity", "Charge activity", 3.0, 1.0, 6.0,
     "Charge: how much more is going on at the top of the build"),
    ("lull_activity", "Lull activity", 0.25, 0.0, 1.0,
     "Lull: how relaxed the motion gets as it fades to dark"),
    ("lull_ember", "Lull ember", 0.0, 0.0, 1.0,
     "Lull: brightness left through the dark (0 = black)"),
    ("drop_shockwave", "Drop shockwave", 1.25, 0.0, 2.0,
     "Drop: size of the centre shockwave and its flood, in the set's colours"),
    ("drop_brightness", "Drop colour brightness", 2.0, 1.0, 3.0,
     "Drop: how much brighter the effect's own colours get on the drop (never whiter)"),
    ("drop_brightness_settle_s", "Drop brightness settle", 1.0, 0.1, 6.0,
     "Drop: seconds for the colour brightness to settle back"),
    ("drop_activity", "Drop activity", 4.0, 1.0, 8.0,
     "Drop: how much more is going on right after the drop"),
    ("drop_settle_s", "Drop settle", 1.6, 0.2, 6.0,
     "Drop: seconds for the activity to settle back"),
    ("white_guard", "White guard", 1.0, 0.0, 1.0,
     "Charge and drop: keep every pixel no whiter than the set's own colour (0 = the effect's own blending)"),
    ("flare_punch_strength", "Flare punch", 1.0, 0.0, 1.0,
     "Lull: how strongly a flare punches through the dark (0 = the dark wins)"),
    ("flare_punch_min_hold_s", "Flare punch hold", lull_dark.DEFAULT_PUNCH_MIN_HOLD_S,
     0.0, 5.0, "Lull: shortest time a flare's punch holds before releasing"),
    ("flare_punch_release_s", "Flare punch release", lull_dark.DEFAULT_PUNCH_RELEASE_S,
     0.0, 5.0, "Lull: seconds a flare's punch takes to fall back into the dark"),
    ("flare_punch_glow", "Flare punch glow", 0.10, 0.0, 1.0,
     "Lull: set-colour fill a flare adds where the dark had taken the light (0 = none)"),
)
TUNABLE_KEYS = tuple(t[0] for t in TUNABLES)

def tunable_fields(**overrides) -> dict:
    """CONFIG_SCHEMA entries for the tunables with an effect's own
    defaults (HOW AN EFFECT JOINS, step 5) — e.g. the Fireworks strip's
    `tunable_fields(lull_ember=0.12)`. Spliced into the effect's own schema,
    they replace the layer's (the most derived schema wins)."""
    unknown = set(overrides) - set(TUNABLE_KEYS)
    if unknown:
        raise KeyError(f"not strip phase tunables: {sorted(unknown)}")
    fields = {}
    for key, _label, default, lo, hi, desc in TUNABLES:
        if key in overrides:
            fields[vol.Optional(key, description=desc,
                                default=overrides[key])] = vol.All(
                vol.Coerce(float), vol.Range(min=lo, max=hi))
    return fields


# The keys SpotFX pushes (never in the registry).
PUSHED_KEYS = ("phase", "phase_progress", *lull_dark.KEYS,
               lull_handoff.DROP_KEY, STRENGTH_KEY, PUNCH_KEY, PUNCH_HOLD_KEY)

HELP_TOPIC = "strip-phases"


class StripFrame(NamedTuple):
    """One frame's layer values, after strength (module docstring)."""
    gain: float = 1.0
    fill: float = 0.0
    wave: float = 0.0
    fade: float = 1.0
    punch_fill: float = 0.0
    guard: float = 0.0
    activity: float = 1.0

    def neutral(self) -> bool:
        return (abs(self.gain - 1.0) <= NEUTRAL_EPS
                and self.fill <= NEUTRAL_EPS and self.wave <= NEUTRAL_EPS
                and abs(self.fade - 1.0) <= NEUTRAL_EPS
                and self.punch_fill <= NEUTRAL_EPS
                and self.guard <= NEUTRAL_EPS
                and abs(self.activity - 1.0) <= NEUTRAL_EPS)


def registry_params(defaults: Optional[dict] = None) -> dict:
    """The config/effect_params.json `params` entries for the tunables —
    what a joining effect registers (HOW AN EFFECT JOINS, step 4), with its
    own `defaults` (an effect class's STRIP_PHASE_DEFAULTS) where it has
    any."""
    defaults = defaults or {}
    out = {}
    for key, label, default, lo, hi, _desc in TUNABLES:
        out[key] = {"label": label, "type": "numeric", "smooth": True,
                    "min": lo, "max": hi,
                    "default": defaults.get(key, default),
                    "help_topic": HELP_TOPIC}
    return out


def _schema() -> vol.Schema:
    fields = {
        vol.Optional(
            "phase",
            description="Charge/lull/drop choreography phase (driven by SpotFX)",
            default="none",
        ): vol.In(list(PHASES)),
        vol.Optional(
            "phase_progress",
            description="Progress through the current phase (ramped by SpotFX)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
        **lull_dark.schema_fields(),
        **lull_handoff.drop_schema_fields(),
        vol.Optional(
            STRENGTH_KEY,
            description="The room's strip phase strength (driven by SpotFX; 0 = off)",
            default=DEFAULT_STRENGTH,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=MAX_STRENGTH)),
        vol.Optional(
            PUNCH_KEY,
            description="A flare landed in the lull (driven by SpotFX; self-resets)",
            default=0,
        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_PUNCH)),
        vol.Optional(
            PUNCH_HOLD_KEY,
            description="The punching flare's own hold, seconds (driven by SpotFX)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=30.0)),
    }
    for key, _label, default, lo, hi, desc in TUNABLES:
        fields[vol.Optional(key, description=desc, default=default)] = vol.All(
            vol.Coerce(float), vol.Range(min=lo, max=hi))
    return vol.Schema(fields)


def _smoothstep(x: float) -> float:
    x = min(1.0, max(0.0, float(x)))
    return x * x * (3.0 - 2.0 * x)


def _clip01(x: float) -> float:
    return min(1.0, max(0.0, float(x)))


def apply_strength(frame: StripFrame, strength: float) -> StripFrame:
    """Every quantity's distance from neutral, times the room's strength —
    0 returns exactly neutral. The white guard scales by min(1, strength)."""
    s = max(0.0, float(strength))
    if s == 1.0:
        return frame
    return StripFrame(
        gain=max(0.0, 1.0 + s * (frame.gain - 1.0)),
        fill=max(0.0, s * frame.fill),
        wave=max(0.0, s * frame.wave),
        fade=max(0.0, 1.0 + s * (frame.fade - 1.0)),
        punch_fill=frame.punch_fill,
        guard=frame.guard * min(1.0, s),
        activity=(max(0.05, 1.0 + s * (frame.activity - 1.0))
                  if frame.activity != 1.0 else 1.0),
    )


def shockwave(n: int, t: float, size: float) -> np.ndarray:
    """The drop's shockwave over `n` pixels, `t` seconds after the mark —
    per-pixel strengths (0..size): a front leaving the centre and reaching
    both ends in DROP_FRONT_S, a set-colour flood behind it."""
    if n <= 0 or size <= 0.0 or t < 0.0:
        return np.zeros(max(n, 0))
    x = np.linspace(0.0, 1.0, n) if n > 1 else np.full(1, 0.5)
    d = np.abs(x - 0.5) * 2.0           # 0 at the centre, 1 at each end
    r = t / DROP_FRONT_S
    front = np.exp(-(((d - r) / DROP_FRONT_WIDTH) ** 2))
    if t > DROP_FRONT_S:
        front = front * (1.0 - _smoothstep((t - DROP_FRONT_S) / DROP_FADE_S))
    flood_amt = DROP_FLOOD * (1.0 - _smoothstep(t / DROP_FLOOD_S))
    flood = np.where(d <= r, flood_amt, 0.0)
    return size * np.maximum(front, flood)


def drop_live_s(settle_s: float, brightness_settle_s: float) -> float:
    """Seconds after its mark a drop still changes the frame."""
    return max(float(settle_s), float(brightness_settle_s),
               DROP_FRONT_S + DROP_FADE_S, DROP_FLOOD_S, DROP_FILL_CARRY_S)


def _peak(rgb: np.ndarray) -> np.ndarray:
    """Brightest channel per row — np.maximum of the columns, several times
    faster than an axis reduce on a strip-sized array."""
    return np.maximum(np.maximum(rgb[:, 0], rgb[:, 1]), rgb[:, 2])


def _floor(rgb: np.ndarray) -> np.ndarray:
    return np.minimum(np.minimum(rgb[:, 0], rgb[:, 1]), rgb[:, 2])


def hue_kept_clip(out: np.ndarray, limit) -> np.ndarray:
    """Scale every pixel whose brightest channel passes `limit` down WHOLE —
    never a per-channel clip (that is how a bright colour bleaches toward
    yellow/white). In place; returns `out`."""
    peak = _peak(out)
    over = peak > limit
    if np.any(over):
        lim = limit[over] if np.ndim(limit) else limit
        out[over] *= (lim / peak[over])[:, None]
    return out


def _hues(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(hue 0..1, max channel, min channel) per row of an (n, 3) array."""
    mx = _peak(rgb)
    mn = _floor(rgb)
    span = mx - mn
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    safe = np.where(span > 0.0, span, 1.0)
    h = np.where(mx == r, ((g - b) / safe) % 6.0,
                 np.where(mx == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0))
    return (h / 6.0) % 1.0, mx, mn


def white_allowance(palette: np.ndarray, bins: int = GUARD_HUE_BINS) -> np.ndarray:
    """For each hue bin, the grey share (min/max channel) the SET'S OWN
    colour at that hue carries — the most a pixel of that hue may have. A
    hue the set never reaches borrows the nearest reached bin's allowance;
    a palette with no colour at all (black) allows nothing."""
    pal = np.asarray(palette, dtype=float).reshape(-1, 3)
    h, mx, mn = _hues(pal)
    lit = mx > GUARD_MIN_LEVEL
    allow = np.full(bins, -1.0)
    grey_palette = lit & ((mx - mn) <= 1e-6)
    if np.any(lit):
        ratio = np.where(lit, mn / np.where(lit, mx, 1.0), 0.0)
        idx = (h * bins).astype(int) % bins
        for b, rt in zip(idx[lit & ~grey_palette], ratio[lit & ~grey_palette]):
            if rt > allow[b]:
                allow[b] = rt
        if np.any(grey_palette):
            # the set itself holds a grey/white: every hue may be that white
            allow = np.maximum(allow, 1.0)
    if np.all(allow < 0.0):
        return np.zeros(bins)
    reached = np.flatnonzero(allow >= 0.0)
    for b in np.flatnonzero(allow < 0.0):
        dist = np.minimum((reached - b) % bins, (b - reached) % bins)
        allow[b] = allow[reached[int(np.argmin(dist))]]
    return allow


def white_guard(out: np.ndarray, allow: np.ndarray, palette: np.ndarray,
                strength: float = 1.0) -> np.ndarray:
    """Pull every pixel whiter than its hue's allowance back to it, keeping
    its hue and its brightest channel: each channel x -> M - (M - x) * k,
    which leaves the brightest channel M and the hue in place and lowers the
    grey share min/max to the allowance. A pixel with no hue (pure grey)
    takes the set's own colour at its place on the strip, at its brightness.
    `strength` blends between nothing (0) and the full pull (1). In place."""
    if strength <= 0.0:
        return out
    h, mx, mn = _hues(out)
    lit = mx > GUARD_MIN_LEVEL
    if not np.any(lit):
        return out
    bins = allow.shape[0]
    a = allow[(h * bins).astype(int) % bins]
    ratio = np.where(lit, mn / np.where(lit, mx, 1.0), 0.0)
    too_white = lit & (ratio > a + 1e-6)
    if not np.any(too_white):
        return out
    span = mx - mn
    grey = too_white & (span <= 1e-6)
    hued = too_white & ~grey
    if np.any(hued):
        m = mx[hued]
        k = (m - a[hued] * m) / span[hued]
        k = 1.0 + strength * (k - 1.0)
        out[hued] = m[:, None] - (m[:, None] - out[hued]) * k[:, None]
    if np.any(grey):
        pal = np.asarray(palette, dtype=float)
        pmx = _peak(pal[grey])
        safe = np.where(pmx > 0.0, pmx, 1.0)
        target = pal[grey] * (mx[grey] / safe)[:, None]
        target[pmx <= 0.0] = 0.0
        out[grey] = out[grey] + strength * (target - out[grey])
    np.clip(out, 0.0, None, out=out)
    return out


@Effect.no_registration
class StripPhase(Effect):
    """The mixin (module docstring). Put it FIRST in a 1-D effect's bases."""

    CONFIG_SCHEMA = _schema()
    _strip_phase = True
    PASSIVE_CONFIG_KEYS = frozenset(PUSHED_KEYS + TUNABLE_KEYS)
    # {"attr name on self": weight} — see HOW AN EFFECT JOINS, step 3.
    STRIP_PHASE_ACTIVITY: dict = {}
    # the effect's own defaults for tunables (step 5) — what its schema's
    # tunable_fields() and its registry_params() both carry
    STRIP_PHASE_DEFAULTS: dict = {}
    # the effect's own drop length (THE PARTICLE STRIPS' PLUMBING)
    STRIP_PHASE_DROP_S: Optional[float] = None

    # ── config: edge detection (also the passive path) ──────────────────────

    def config_updated(self, config):
        self._strip_phase_config(config)

    def _passive_config_updated(self, config):
        self._strip_phase_config(config)

    def _strip_phase_config(self, config):
        new_phase = config.get("phase", "none")
        new_punch = int(config.get(PUNCH_KEY, 0) or 0)
        self.phase_progress = _clip01(config.get("phase_progress", 0.0) or 0.0)
        if not hasattr(self, "_sp_phase"):
            # creation baseline: a stale persisted phase or punch must never
            # edge-fire on a fresh instance (the effect is born at "none";
            # SpotFX's arm write right after a cut is the real edge)
            self._sp_phase = "none"
            self._sp_pending = None
            self._sp_t = 0.0
            self._sp_done_t = None
            self._sp_drop_t = None
            self._sp_drop_fill = 0.0
            self._sp_lull_from = (1.0, 0.0, 1.0)   # gain, fill, activity
            self._sp_raw = (1.0, 0.0, 1.0)
            self._sp_punch_seen = new_punch
            self._sp_punch_pending = False
            self._sp_punch_t = None
            self._sp_punch_hold = 0.0
            self._sp_frame = None
            self._sp_activity = 1.0
            self._sp_saved = None
            self._sp_clock = 0.0
            self._sp_guard_key = None
            self._sp_guard_allow = None
            self._sp_lull_timing = None
            self._sp_punch_level = 0.0
            return
        self._sp_pending = new_phase if new_phase != self._sp_phase else None
        if new_punch != self._sp_punch_seen:
            self._sp_punch_seen = new_punch
            if new_punch > 0:
                self._sp_punch_pending = True

    # ── per frame ───────────────────────────────────────────────────────────

    def _strip_phase_to_none(self, released: bool):
        """Back to the effect's own look: the orphan watchdog let go of a
        charge or lull (`released`), or the effect's own drop length ran
        out. Writes the key so an identical later arm edges again."""
        prev = self._sp_phase
        self._sp_phase = "none"
        self._sp_punch_t = None
        self._apply_config({"phase": "none", "phase_progress": 0.0},
                           validate=False, fire_event=False)
        self._strip_phase_enter("none", prev, released)

    def _strip_phase_release(self):
        """The orphan watchdog fired: go back to the effect's own look."""
        _LOGGER.info("%s: strip %s watchdog release after %.1fs",
                     type(self).__name__, self._sp_phase, self._sp_t)
        self._strip_phase_to_none(released=True)

    def _strip_phase_enter(self, phase: str, prev: str, released: bool):
        """The phase key edged (THE PARTICLE STRIPS' PLUMBING): called once
        per edge, before this frame's render(), after the layer's own edge.
        An effect with choreography of its own starts it here. Default:
        nothing (Melt, Power)."""

    def _strip_phase_edge(self, pend):
        prev = self._sp_phase
        self._sp_phase = pend
        self._sp_t = 0.0
        self._sp_done_t = None
        if pend == "charge":
            self._sp_drop_t = None
            self._sp_punch_t = None
        elif pend == "lull":
            # ease from wherever the charge (or a drop still settling) left
            # the strip — never a jump at the lull's edge
            live = prev == "charge" or self._sp_drop_t is not None
            self._sp_lull_from = self._sp_raw if live else (1.0, 0.0, 1.0)
            self._sp_drop_t = None
        elif pend == "drop":
            self._sp_drop_t = 0.0
            self._sp_drop_fill = self._sp_raw[1]
            self._sp_punch_t = None
        else:   # "none": the drop's own clock keeps running
            self._sp_punch_t = None
        self._strip_phase_enter(pend, prev, False)

    def _strip_phase_compute(self, dt: float) -> Optional[StripFrame]:
        """Advance the layer's clocks one frame and return this frame's
        values (after strength), or None when nothing is live."""
        cfg = self._config
        pend = self._sp_pending
        if pend is not None:
            self._sp_pending = None
            if pend != self._sp_phase:
                self._strip_phase_edge(pend)
        if self._sp_punch_pending:
            self._sp_punch_pending = False
            if self._sp_phase == "lull":
                self._sp_punch_t = 0.0
                self._sp_punch_hold = float(cfg.get(PUNCH_HOLD_KEY, 0.0) or 0.0)
                self._strip_phase_on_punch()
            # self-reset so an identical later poke edges again
            self._sp_punch_seen = 0
            self._config = {**self._config, PUNCH_KEY: 0}
            cfg = self._config

        phase = self._sp_phase
        progress = _clip01(cfg.get("phase_progress", 0.0) or 0.0)
        if phase != "none":
            self._sp_t += dt
            due, self._sp_done_t = particle_handoff.phase_release_due(
                phase, progress, self._sp_t, self._sp_done_t)
            if due:
                self._strip_phase_release()
                phase = "none"
            elif (phase == "drop" and self.STRIP_PHASE_DROP_S is not None
                    and self._sp_t >= self.STRIP_PHASE_DROP_S):
                # the effect's own drop has run its length: self-reset
                self._strip_phase_to_none(released=False)
                phase = "none"
        if self._sp_drop_t is not None:
            self._sp_drop_t += dt
            if self._sp_drop_t > drop_live_s(cfg["drop_settle_s"],
                                             cfg["drop_brightness_settle_s"]):
                self._sp_drop_t = None
        if self._sp_punch_t is not None:
            self._sp_punch_t += dt

        gain, fill, act, wave, fade, guard = 1.0, 0.0, 1.0, 0.0, 1.0, 0.0
        in_lull = False
        self._sp_punch_level = 0.0
        self._sp_lull_timing = None
        if phase == "charge":
            gain = 1.0 + (float(cfg["charge_brightness"]) - 1.0) * progress
            fill = float(cfg["charge_fill"]) * progress
            act = 1.0 + (float(cfg["charge_activity"]) - 1.0) * progress
            guard = float(cfg["white_guard"])
            self._sp_raw = (gain, fill, act)
        elif phase == "lull":
            in_lull = True
            timing = lull_dark.lull_timing(cfg, progress, self._sp_t,
                                           LEGACY_DARK_AT)
            self._sp_lull_timing = timing
            a = 1.0 if timing.dark else _smoothstep(timing.approach)
            g0, fill0, act0 = self._sp_lull_from
            gain = g0 + (1.0 - g0) * a
            fill = fill0 * (1.0 - a)
            act = act0 + (float(cfg["lull_activity"]) - act0) * a
            fade = 1.0 + (float(cfg["lull_ember"]) - 1.0) * a
            self._sp_raw = (gain * fade, fill, act)
        elif self._sp_drop_t is not None:
            t = self._sp_drop_t
            kb = 1.0 - _smoothstep(t / max(0.05, float(cfg["drop_brightness_settle_s"])))
            ka = 1.0 - _smoothstep(t / max(0.05, float(cfg["drop_settle_s"])))
            gain = 1.0 + (float(cfg["drop_brightness"]) - 1.0) * kb
            act = 1.0 + (float(cfg["drop_activity"]) - 1.0) * ka
            fill = self._sp_drop_fill * (1.0 - _smoothstep(t / DROP_FILL_CARRY_S))
            told = lull_handoff.drop_intensity(cfg)
            size = UNTOLD_DROP_INTENSITY if told is None else told
            wave = float(cfg["drop_shockwave"]) * size
            guard = float(cfg["white_guard"])
            self._sp_raw = (gain, fill, act)
        else:
            self._sp_raw = (1.0, 0.0, 1.0)

        frame = apply_strength(
            StripFrame(gain=gain, fill=fill, wave=wave, fade=fade,
                       guard=guard, activity=act),
            float(cfg.get(STRENGTH_KEY, DEFAULT_STRENGTH)))

        if in_lull and self._sp_punch_t is not None:
            env = lull_dark.punch_envelope(
                self._sp_punch_t, self._sp_punch_hold,
                float(cfg["flare_punch_min_hold_s"]),
                float(cfg["flare_punch_release_s"]))
            p = float(cfg["flare_punch_strength"]) * env
            self._sp_punch_level = p
            if p > 0.0:
                taken = 1.0 - min(1.0, frame.fade)
                act = frame.activity
                frame = frame._replace(
                    fade=max(frame.fade, p),
                    activity=act + (1.0 - act) * p if act < 1.0 else act,
                    punch_fill=float(cfg["flare_punch_glow"]) * p * taken)
            elif self._sp_punch_t > lull_dark.PUNCH_ATTACK_S:
                self._sp_punch_t = None
        elif not in_lull:
            self._sp_punch_t = None

        return None if frame.neutral() else frame

    def _strip_phase_on_punch(self):
        """A flare punch just opened in a lull (called once per poke, before
        this frame's render()). The layer's own answer is the fade and glow
        in the output stage; an effect may add content of its own here (the
        Black Hole strip's ring burst). Default: nothing."""

    def _strip_phase_punch(self) -> float:
        """How far a flare punch is open this frame, 0..1 ("Flare punch" x
        the envelope; 0 outside a lull) — for an effect whose content
        answers the punch over its length (the Orbits strip's collapsed
        blob springing back out)."""
        return float(getattr(self, "_sp_punch_level", 0.0))

    def _strip_phase_lull(self) -> Optional[lull_dark.LullTiming]:
        """Where this frame's lull stands against the room's dark point —
        the EXACT timing the layer fades by (computed before render() on the
        layer's own clock), or None outside a lull. An effect that changes
        its own content at the dark point (stops spawning, tapers a
        formation) reads this, so its content and the fade can never
        disagree about when the strip is dark."""
        return getattr(self, "_sp_lull_timing", None)

    def _strip_phase_before_render(self):
        """Effect._render, before render(): advance the layer, then apply
        this frame's activity to the effect's named attributes."""
        dt = max(0.0, float(getattr(self, "passed", 0.0) or 0.0))
        self._sp_clock += dt
        frame = self._strip_phase_compute(dt)
        self._sp_frame = frame
        act = 1.0 if frame is None else frame.activity
        self._sp_activity = act
        self._sp_saved = None
        if act != 1.0 and self.STRIP_PHASE_ACTIVITY:
            saved = {}
            for name, weight in self.STRIP_PHASE_ACTIVITY.items():
                cur = getattr(self, name, None)
                if not isinstance(cur, (int, float)) or isinstance(cur, bool):
                    continue
                saved[name] = cur
                scaled = cur * max(0.0, 1.0 + float(weight) * (act - 1.0))
                setattr(self, name,
                        int(round(scaled)) if isinstance(cur, int) else scaled)
            self._sp_saved = saved

    def _strip_phase_after_render(self):
        saved = self._sp_saved
        if saved:
            for name, value in saved.items():
                setattr(self, name, value)
        self._sp_saved = None

    def _strip_phase_palette(self, n: int) -> Optional[np.ndarray]:
        """The effect's own gradient along the strip, (n, 3) 0..255 — or
        None for an effect with no gradient (fill, wave and guard skip)."""
        getter = getattr(self, "get_gradient_color_vectorized1d", None)
        if getter is None:
            return None
        try:
            pal = np.asarray(getter(np.linspace(0.0, 1.0, n)), dtype=float)
        except Exception:                                # noqa: BLE001
            return None
        return pal if pal.shape == (n, 3) else None

    def _strip_phase_allowance(self, palette: np.ndarray) -> np.ndarray:
        """The white guard's per-hue allowance, built once per gradient."""
        key = (self._config.get("gradient"), palette.shape[0])
        if self._sp_guard_key != key or self._sp_guard_allow is None:
            self._sp_guard_allow = white_allowance(palette)
            self._sp_guard_key = key
        return self._sp_guard_allow

    def _strip_phase_stage(self, pixels):
        """Effect.get_pixels, after background and brightness (module
        docstring, THE ORDER)."""
        frame = self._sp_frame
        if frame is None or pixels is None:
            return pixels
        out = np.array(pixels, dtype=float, copy=True)
        n = out.shape[0]
        limit = np.maximum(_peak(out), 255.0)
        if frame.gain != 1.0:
            out *= frame.gain
            hue_kept_clip(out, limit)
        needs_palette = (frame.fill > 0.0 or frame.wave > 0.0
                         or frame.punch_fill > 0.0 or frame.guard > 0.0)
        palette = self._strip_phase_palette(n) if needs_palette else None
        bright = float(self.brightness if self.brightness is not None else 1.0)
        if palette is not None:
            colour = palette * bright
            if frame.fill > 0.0:
                hz = SHIMMER_HZ_START + (SHIMMER_HZ_END - SHIMMER_HZ_START) * _clip01(
                    self._config.get("phase_progress", 0.0) or 0.0)
                x = np.linspace(0.0, 1.0, n)
                shimmer = 1.0 + SHIMMER_DEPTH * np.sin(
                    2.0 * math.pi * (hz * self._sp_clock + SHIMMER_SPATIAL * x))
                own = np.clip(_peak(out) / 255.0, 0.0, 1.0)
                out += colour * (frame.fill * shimmer * (1.0 - own))[:, None]
            if frame.wave > 0.0 and self._sp_drop_t is not None:
                level = shockwave(n, self._sp_drop_t, frame.wave)
                wave_px = colour * level[:, None]
                hue_kept_clip(wave_px, 255.0)
                brighter = _peak(wave_px) > _peak(out)
                out[brighter] = wave_px[brighter]
        if frame.fade != 1.0:
            out *= frame.fade
        if palette is not None and frame.punch_fill > 0.0:
            own = np.clip(_peak(out) / 255.0, 0.0, 1.0)
            out += (palette * bright) * (frame.punch_fill * (1.0 - own))[:, None]
        if palette is not None and frame.guard > 0.0:
            # the device clips each channel at 255, which turns an over-full
            # colour white — while guarded, the stage does that clip itself,
            # hue-kept, so nothing reaches the device past full
            hue_kept_clip(out, 255.0)
            white_guard(out, self._strip_phase_allowance(palette), palette,
                        frame.guard)
            limit = 255.0
        hue_kept_clip(out, limit)
        return out
