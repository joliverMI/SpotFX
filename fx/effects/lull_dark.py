"""THE LULL'S DARK POINT — one rule for every lull effect that goes dark.

His ask, 2026-10-07 (the Admiral, verbatim): "For the lull effects like
black hole and squiggles, (and pulse) we have full darkness half way
through the lull. Sometimes the lull is very extended and it's too long to
be fully dark. Instead of always setting the dark point to half way through
the lull, set a max time for that portion to 3 seconds (make this something
sonic can change). So if we have a 20 second lull ... Now it would be 17
seconds of expansion and 3 seconds of dark. Pulse should match, so it's
only pitch black for 3 seconds. Do just these 3 effects for now, but
prepare clear method for doing it with others and future ones."

THE RULE (`dark_hold_s` / `dark_start_s`, the ONE definition):

    dark_hold  = min(lull / 2, max_dark)
    dark_start = lull - dark_hold          # the approach before it

so a 20 s lull is 17 s of approach and 3 s of dark, and a 4 s lull keeps
its half-and-half 2 s + 2 s. `max_dark` is the room setting
`RoomControlState.lull_dark_max_s` (default 3.0, Sonic-editable); 0 means
the lull only reaches dark on its drop.

WHY THE EFFECT HAS TO BE TOLD. An effect only ever sees `phase_progress`,
which SpotFX ramps 0 -> 1 over ~90% of the real gap to the drop and then
HANGS at 1.0 (spectra scene_response._phase_ramp_ms). A fixed progress
fraction therefore cannot express "3 s before the drop" — it can only ever
mean a fixed share of the lull. So SpotFX computes the rule at the lull's
own arm write (scene_response._drive_phase, the one place a phase is
written) and pushes two plain numbers alongside `phase`/`phase_progress`:

- `lull_dark_s`: seconds from the lull's start to its dark point;
- `lull_ramp_s`: how long SpotFX's progress ramp runs (seconds) — the end
  of the lull's movement, which `after` runs up to.

Both default to 0 = NOT TOLD (an older SpotFX, a hand-written test, a LedFX
UI scrub): the effect then behaves exactly as it did before this rule
existed, at its own `legacy_dark_at` progress — byte-identical, so nothing
changes for a write that does not carry the keys.

SECONDS INTO THE LULL ARE THE EFFECT'S OWN CLOCK, NOT `phase_progress`.
Once told, an effect measures the lull on its own seconds-in-phase (reset on
the lull's edge, advanced every rendered frame), never by turning progress
back into seconds: a lull longer than ten times the cap has its dark point
inside the hang, where progress no longer moves (a 40 s lull's dark point
sits at 37 s, after its 36 s ramp) — only a clock can find it. While the
ramp runs the two agree. (PR #365 also leaned on the clock because a lull
after a completed charge used to start its progress at 1.0; that was fixed
at its root in the shared tween engine — fx/VENDOR.md #58 — so progress is
honest again for every phase effect, and the orphan watchdog judges a told
lull by its progress like any other.)

HOW A LULL EFFECT OPTS IN (existing or future — one call, plus two lines):
  1. splice `**lull_dark.schema_fields()` into its CONFIG_SCHEMA (and
     `*lull_dark.KEYS` into ADVANCED_KEYS, beside `phase_progress`);
  2. add its registry name to `fx.device_model.LULL_DARK_EFFECTS`, which is
     what makes SpotFX push the two keys on its lull arm;
  3. read `lull_dark.lull_timing(self._config, progress, phase_t,
     legacy_dark_at=<the progress its dark point sat at before>)` — with
     `phase_t` its own seconds since the lull's edge — wherever
     it used a fixed progress fraction for its dark point. `approach` runs
     0 -> 1 from the lull's start to the dark point (an expansion, a fade, a
     squash), `dark` says the dark portion has begun, and `after` runs 0 -> 1
     from the dark point to the end of SpotFX's ramp (a second movement
     inside the dark; no opted-in effect uses one today — Squiggles' old
     line-to-dot pinch was retired with its CRT lull, 2026-10-11).
Black Hole, Squiggles and Pulse were his three ("just these 3 for now");
since 2026-10-11 every strip phase member (fx/effects/strip_phase.py,
fx.device_model.STRIP_PHASE_EFFECTS — Melt, Power and, since the strip
phase plan's phase 2, blackhole1d) reads the same rule through the shared
strip layer. The FLARE PUNCH envelope at the end of this module
is the same kind of one-definition rule for "a flare in the dark".
"""

from __future__ import annotations

from typing import Mapping, NamedTuple

import voluptuous as vol

RAMP_KEY = "lull_ramp_s"
DARK_KEY = "lull_dark_s"
KEYS = (RAMP_KEY, DARK_KEY)

DEFAULT_MAX_DARK_S = 3.0

# A dark-to-ramp-end span shorter than this has no room for a second
# movement: `after` jumps straight to 1 at the dark point.
MIN_AFTER_SPAN_S = 1e-3


class LullTiming(NamedTuple):
    approach: float   # 0 -> 1, lull start -> dark point
    dark: bool        # the dark portion has begun
    after: float      # 0 -> 1, dark point -> the end of SpotFX's ramp


def dark_hold_s(lull_s: float, max_dark_s: float) -> float:
    """How long the lull holds dark: half the lull, never more than the cap."""
    lull_s = max(0.0, float(lull_s))
    return min(lull_s / 2.0, max(0.0, float(max_dark_s)))


def dark_start_s(lull_s: float, max_dark_s: float) -> float:
    """Seconds from the lull's start to its dark point."""
    lull_s = max(0.0, float(lull_s))
    return lull_s - dark_hold_s(lull_s, max_dark_s)


def keys_for(lull_s: float, ramp_s: float, max_dark_s: float) -> dict:
    """The two config keys SpotFX pushes on a lull arm (see the module
    docstring). `lull_s` is the real lull length (the gap to its drop);
    `ramp_s` how long the phase_progress ramp runs."""
    return {
        RAMP_KEY: max(0.0, float(ramp_s)),
        DARK_KEY: dark_start_s(lull_s, max_dark_s),
    }


def schema_fields() -> dict:
    """CONFIG_SCHEMA entries for the two pushed keys — spliced into an
    opted-in effect's schema so a validated write keeps them. Like the phase
    keys, never part of the effect-parameter registry: only the lull arm
    write carries them."""
    return {
        vol.Optional(
            RAMP_KEY,
            description="Lull: seconds the phase_progress ramp runs (driven by SpotFX; 0 = not told)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Optional(
            DARK_KEY,
            description="Lull: seconds from the lull's start to its dark point (driven by SpotFX)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
    }


def told(config: Mapping) -> bool:
    """SpotFX pushed this lull's timing (the rule applies), rather than the
    effect falling back to its legacy progress fraction."""
    return float(config.get(RAMP_KEY, 0.0) or 0.0) > 0.0


def _clip01(x: float) -> float:
    return min(1.0, max(0.0, x))


def lull_timing(config: Mapping, progress: float, phase_t: float,
                legacy_dark_at: float) -> LullTiming:
    """Where this lull is relative to its dark point (module docstring).
    `phase_t` is the effect's own seconds since the lull's edge (used once
    SpotFX has told it the lull's timing); `legacy_dark_at` is the progress
    the effect's dark point sat at before the rule — used verbatim when
    SpotFX did not push the keys."""
    p = _clip01(float(progress))
    ramp_s = float(config.get(RAMP_KEY, 0.0) or 0.0)
    dark_s = float(config.get(DARK_KEY, 0.0) or 0.0)
    if not told(config):
        legacy = float(legacy_dark_at)
        if legacy <= 0.0:
            return LullTiming(1.0, True, p)
        dark = p >= legacy
        if legacy >= 1.0:
            after = 1.0 if dark else 0.0
        else:
            after = _clip01((p - legacy) / (1.0 - legacy))
        return LullTiming(min(p / legacy, 1.0), dark, after)
    t = max(0.0, float(phase_t))
    if dark_s <= 0.0:
        approach = 1.0
    else:
        approach = min(t / dark_s, 1.0)
    dark = t >= dark_s
    span = ramp_s - dark_s
    if span > MIN_AFTER_SPAN_S:
        after = _clip01((t - dark_s) / span)
    else:
        after = 1.0 if dark else 0.0
    return LullTiming(approach, dark, after)


# ── A FLARE IN THE LULL'S DARK PUNCHES THROUGH ──────────────────────────────
# The Admiral, 2026-10-11 (strip phase plan, his answer 5): a flare that
# lands while a lull is darkening — or already dark — shows at full
# strength, and when it is over the lull's own curve takes the light back
# exactly where the lull has got to. The lull's timing (dark point, cap,
# drop) never moves. Defined HERE, beside the dark point, so every lull-dark
# member reads the same envelope AND the same runtime (FlarePunch): the strip
# layer (fx/effects/strip_phase.py) since the strip phase plan's phase 1, the
# crystal's Black Hole and Squiggles and the Pulse singles since its phase 5
# (his approval: "so a flare in a dark room lights everything together").
#
# The envelope rises over PUNCH_ATTACK_S, holds for max(min_hold, the
# flare's own hold), then releases over `release_s` (smoothstep). SpotFX
# pokes it (scene_response's flare pipeline, only while a lull is armed, only
# on a virtual the flare batch actually wrote to, only for an effect in
# fx.device_model.FLARE_PUNCH_EFFECTS).
#
# HOW A LULL EFFECT TAKES THE PUNCH (existing or future):
#   1. splice `**punch_schema_fields()` into its CONFIG_SCHEMA and
#      `*PUNCH_KEYS` into ADVANCED_KEYS (the two pushed keys; the three
#      PUNCH_TUNABLES are ordinary params);
#   2. add its registry name to fx.device_model.FLARE_PUNCH_EFFECTS (SpotFX
#      pokes it from then on) and register `punch_registry_params()` in
#      config/effect_params.json (Sonic reaches the three tunables through
#      set_scene_entry_param);
#   3. hold one `FlarePunch` (built in its creation pass), `note()` the poke
#      key in config_updated, `consume()` + `advance()` + `level()` once a
#      frame, and let its own lull darkness give way to the level — the
#      lull's own curve keeps running underneath, so the release lands back
#      exactly where the lull has got to.

PUNCH_ATTACK_S = 0.04
DEFAULT_PUNCH_MIN_HOLD_S = 0.5
DEFAULT_PUNCH_RELEASE_S = 0.8


def _smoothstep(x: float) -> float:
    x = _clip01(x)
    return x * x * (3.0 - 2.0 * x)


def punch_envelope(t: float, hold_s: float,
                   min_hold_s: float = DEFAULT_PUNCH_MIN_HOLD_S,
                   release_s: float = DEFAULT_PUNCH_RELEASE_S) -> float:
    """How much of a flare punch is showing `t` seconds after it landed:
    0 -> 1 over PUNCH_ATTACK_S, 1 through the hold, then a smoothstep back
    to 0 over `release_s`. 0 for t < 0 and once fully released."""
    t = float(t)
    if t < 0.0:
        return 0.0
    if t < PUNCH_ATTACK_S:
        return t / PUNCH_ATTACK_S
    hold = max(float(min_hold_s), float(hold_s or 0.0))
    t_rel = t - PUNCH_ATTACK_S - hold
    if t_rel <= 0.0:
        return 1.0
    release = max(0.0, float(release_s))
    if release <= 0.0 or t_rel >= release:
        return 0.0
    return 1.0 - _smoothstep(t_rel / release)


def punch_length_s(hold_s: float,
                   min_hold_s: float = DEFAULT_PUNCH_MIN_HOLD_S,
                   release_s: float = DEFAULT_PUNCH_RELEASE_S) -> float:
    """Seconds from a punch landing until it has fully released."""
    return (PUNCH_ATTACK_S + max(float(min_hold_s), float(hold_s or 0.0))
            + max(0.0, float(release_s)))


# The poke SpotFX writes (a self-resetting count, the `burst_rockets` shape)
# and the punching flare's own hold. Never in the param registry.
PUNCH_KEY = "flare_punch"
PUNCH_HOLD_KEY = "flare_punch_hold_s"
PUNCH_KEYS = (PUNCH_KEY, PUNCH_HOLD_KEY)
MAX_PUNCH = 1000
MAX_PUNCH_HOLD_S = 30.0

PUNCH_HELP_TOPIC = "flare-punch"

# The punch's tunables: (key, label, default, min, max, description). One
# table for every member (the strip layer splices it into its own TUNABLES),
# so the strips and the crystal can never mean different things by them.
PUNCH_TUNABLES = (
    ("flare_punch_strength", "Flare punch", 1.0, 0.0, 1.0,
     "Lull: how strongly a flare punches through the dark (0 = the dark wins)"),
    ("flare_punch_min_hold_s", "Flare punch hold", DEFAULT_PUNCH_MIN_HOLD_S,
     0.0, 5.0, "Lull: shortest time a flare's punch holds before releasing"),
    ("flare_punch_release_s", "Flare punch release", DEFAULT_PUNCH_RELEASE_S,
     0.0, 5.0, "Lull: seconds a flare's punch takes to fall back into the dark"),
)
PUNCH_TUNABLE_KEYS = tuple(t[0] for t in PUNCH_TUNABLES)


def punch_poke_fields() -> dict:
    """CONFIG_SCHEMA entries for the two pushed keys (never registered)."""
    return {
        vol.Optional(
            PUNCH_KEY,
            description="A flare landed in the lull (driven by SpotFX; self-resets)",
            default=0,
        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_PUNCH)),
        vol.Optional(
            PUNCH_HOLD_KEY,
            description="The punching flare's own hold, seconds (driven by SpotFX)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=MAX_PUNCH_HOLD_S)),
    }


def punch_tunable_fields() -> dict:
    """CONFIG_SCHEMA entries for the three PUNCH_TUNABLES."""
    return {
        vol.Optional(key, description=desc, default=default): vol.All(
            vol.Coerce(float), vol.Range(min=lo, max=hi))
        for key, _label, default, lo, hi, desc in PUNCH_TUNABLES
    }


def punch_schema_fields() -> dict:
    """Everything a lull effect splices in to take the punch (step 1)."""
    return {**punch_poke_fields(), **punch_tunable_fields()}


def punch_registry_params(help_topic: str = PUNCH_HELP_TOPIC) -> dict:
    """The config/effect_params.json `params` entries for PUNCH_TUNABLES
    (step 2) — the one place their registry shape is derived from."""
    return {
        key: {"label": label, "type": "numeric", "smooth": True,
              "min": lo, "max": hi, "default": default,
              "help_topic": help_topic}
        for key, label, default, lo, hi, _desc in PUNCH_TUNABLES
    }


class FlarePunch:
    """ONE FLARE PUNCH's runtime, the same for every member (step 3): the
    poke's edge detection, its clock and its level.

    - `note(value)` from config_updated: a CHANGED, nonzero poke arms;
    - `consume(in_lull, hold_s)` once a frame, before the effect reads the
      level: an armed poke opens the envelope only while a lull is running
      (outside a lull a poke does nothing) and is spent either way. Returns
      True when it opened (the effect may answer with content of its own);
      the effect then writes the poke key back to 0 (`spent` says so), so
      an identical later poke edges again;
    - `advance(dt)` moves the open punch's clock;
    - `level(in_lull, config)` is strength x the envelope (0 outside a lull
      or once released — the punch then closes itself).
    """

    __slots__ = ("seen", "pending", "t", "hold", "spent")

    def __init__(self, seen: int = 0):
        # creation baseline: a stale persisted poke never fires on a fresh
        # instance
        self.seen = int(seen or 0)
        self.pending = False
        self.t = None
        self.hold = 0.0
        self.spent = False

    def note(self, value) -> None:
        value = int(value or 0)
        if value != self.seen:
            self.seen = value
            if value > 0:
                self.pending = True

    def consume(self, in_lull: bool, hold_s: float = 0.0) -> bool:
        self.spent = False
        if not self.pending:
            return False
        self.pending = False
        self.seen = 0
        self.spent = True
        if not in_lull:
            return False
        self.t = 0.0
        self.hold = max(0.0, float(hold_s or 0.0))
        return True

    def advance(self, dt: float) -> None:
        if self.t is not None:
            self.t += max(0.0, float(dt))

    def close(self) -> None:
        self.t = None

    @property
    def open(self) -> bool:
        return self.t is not None

    def level(self, in_lull: bool, config: Mapping) -> float:
        if self.t is None:
            return 0.0
        if not in_lull:
            self.t = None
            return 0.0
        env = punch_envelope(
            self.t, self.hold,
            float(config.get("flare_punch_min_hold_s",
                             DEFAULT_PUNCH_MIN_HOLD_S)),
            float(config.get("flare_punch_release_s",
                             DEFAULT_PUNCH_RELEASE_S)))
        p = float(config.get("flare_punch_strength", 1.0)) * env
        if p <= 0.0 and self.t > PUNCH_ATTACK_S:
            self.t = None
        return max(0.0, p)
