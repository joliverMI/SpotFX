"""THE WORD SHAPE TOLD KEYS — how an effect is TOLD that a sung word has a
shape, and the one envelope every effect forms, holds and releases it on.

Built 2026-11-15 (Word Shapes plan row W0.1, sections 2.3 and 2.4). A sung
word that reaches a shape fires the showing scene's Words response, and the
Word Shape kind writes these six keys to every live effect that knows
shapes (`WORD_SHAPE_EFFECTS`, wave 1). The effect then runs the whole form,
hold and release on its OWN clock and resets itself after — SpotFX writes
once and says nothing more, exactly as `fx/effects/pre_drop.py` and
`fx/effects/lull_handoff.py` already work.

THE KEYS

- `word_shape` (str): the shape's id, as `fx/effects/word_shapes.py` knows
  it ("heart"); "" = no shape, and so is any id this LedFX build does not
  know (`told()` returns None for both, so an older fx never draws a shape
  it cannot build).
- `word_shape_seq` (int): a counter SpotFX bumps per shape event, so two
  words of the SAME shape back to back both read as a fresh edge. An effect
  watches this, never the id, to decide "a new shape just arrived".
- `word_shape_form_s` (float s): the forming time, already Energy-paced by
  the engine (0.9 s quiet to 0.5 s loud) and already the larger of that and
  the showing effect's own minimum. The engine fires the band EARLY by
  exactly this much (a LEAD: positive = earlier,
  `docs/SPECTRA_TIMING_CONVENTIONS.md`), so the shape completes ON the word.
- `word_shape_hold_s` (float s): how long it stands complete — the sung
  phrase, clamped (0.8 to 2.0 s).
- `word_shape_release_s` (float s): how long it takes to let go (1.5x the
  form by default).
- `word_shape_level` (float 0..1): the word's Energy. Size, spark counts
  and anything else that should be bigger when the room is loud scale with
  it. Never 0 when told — SpotFX floors it at LEVEL_FLOOR — so 0 means
  only "not told".

THE ENVELOPE. `envelope(t, form, hold, release)` is the ONE motion law for
all of it: 0 -> 1 over the form on a smoothstep, 1 through the hold, 1 -> 0
over the release on a smoothstep, 0 after. Zero speed at both ends of both
ramps is what keeps a shape from starting or stopping with a step (the
plan's "no jump anywhere", the claim he checks in the room), and every
effect reading the same function is what keeps Black Hole's horizon, STAR's
rotation governor and Fish's trail brightness arriving together.

THREE RULES (`lull_dark.py`'s, kept identical so there is one way an effect
is told anything):

1. KEYS RIDE ONLY THE DEDICATED WRITE. Never in config/effect_params.json,
   never on an editor surface or a band patch. An adopter splices
   `**schema_fields()` into its CONFIG_SCHEMA and `*KEYS` into
   ADVANCED_KEYS (and into PASSIVE_CONFIG_KEYS for a strip phase member) so
   a validated write keeps them and nothing else can set them.
2. EVERY MEMBER GETS EVERY KEY ON EVERY WRITE, even at the default
   (`NOT_TOLD`). `Effect._apply_config` partial-merges, so one song's
   `word_shape: "heart"` would otherwise still be standing at the next
   word; re-writing the resolved value every time is what makes the last
   shape forgettable.
3. NOT TOLD IS THE EFFECT'S OWN BEHAVIOUR. An older SpotFX, a hand test, a
   LedFX UI scrub, a word that lost the roll: no keys, or the defaults, and
   the effect renders byte for byte what it renders today.

`word_shape` is a plain string in the schema ON PURPOSE, not a `vol.In` of
the known ids: a rejected key drops the WHOLE write (`pre_drop.py`'s own
reason for not adding a `phase` value), so an id from a newer SpotFX must
fall through to "not told" rather than take the rest of the write with it.

HOW AN EFFECT OPTS IN (`fish` is the first, plan row W1.4):
  1. the schema fields and ADVANCED_KEYS (rule 1);
  2. its registry name in `fx.device_model.WORD_SHAPE_EFFECTS`;
  3. its own `word_shape_size` (and `word_shape_few` where the plan gives it
     one) as REGISTERED params in config/effect_params.json — but NOT its
     minimum form: that lives in `fx.device_model.WORD_SHAPE_FORM_MIN_S`,
     keyed by registry name, because SpotFX's planner needs it before it
     has asked any effect anything (it is what decides the lead) and
     because a Sonic-tellable number would let the room be retuned into a
     shape that cannot assemble in time;
  4. read `told(self._config)` each frame, `envelope(...)` for where the
     shape is, and `fx.effects.word_shapes.get(told.shape)` for the
     geometry.
"""
from __future__ import annotations

from typing import Mapping, NamedTuple, Optional

import numpy as np
import voluptuous as vol

from fx.effects import word_shapes

SHAPE_KEY = "word_shape"
SEQ_KEY = "word_shape_seq"
FORM_KEY = "word_shape_form_s"
HOLD_KEY = "word_shape_hold_s"
RELEASE_KEY = "word_shape_release_s"
LEVEL_KEY = "word_shape_level"
KEYS = (SHAPE_KEY, SEQ_KEY, FORM_KEY, HOLD_KEY, RELEASE_KEY, LEVEL_KEY)

# The plan's own defaults (section 2.4), used when SpotFX tells a shape but
# not a time — never as a substitute for being told.
DEFAULT_FORM_S = 0.9
DEFAULT_HOLD_S = 0.8
DEFAULT_RELEASE_RATIO = 1.5

# Longest anything here may be told, so a bad number cannot leave a shape
# standing on the panel for a whole song.
MAX_SECONDS = 30.0

# A told level is never pushed below this, so 0 can only mean "not told"
# (rule 3) rather than also meaning "a silent word".
LEVEL_FLOOR = 0.01

NOT_TOLD = {SHAPE_KEY: "", SEQ_KEY: 0, FORM_KEY: 0.0, HOLD_KEY: 0.0,
            RELEASE_KEY: 0.0, LEVEL_KEY: 0.0}


class WordShapeTold(NamedTuple):
    """What one shape write says. `shape` is always an id
    `fx.effects.word_shapes.get()` will build."""

    shape: str
    seq: int
    form_s: float
    hold_s: float
    release_s: float
    level: float

    @property
    def total_s(self) -> float:
        """Form plus hold plus release — the whole shape, from the first
        frame it moves to the last frame it is visible."""
        return self.form_s + self.hold_s + self.release_s


def keys_for(shape: str, seq: int, form_s: float, hold_s: float,
             release_s: float, level: float) -> dict:
    """The six keys SpotFX pushes on a shape write (rule 2: all six, every
    time). `shape=""` is the clearing write and zeroes the rest."""
    if not str(shape or ""):
        return dict(NOT_TOLD)
    return {
        SHAPE_KEY: str(shape),
        SEQ_KEY: max(0, int(seq)),
        FORM_KEY: _clamp_s(form_s),
        HOLD_KEY: _clamp_s(hold_s),
        RELEASE_KEY: _clamp_s(release_s),
        LEVEL_KEY: min(1.0, max(LEVEL_FLOOR, float(level or 0.0))),
    }


def schema_fields() -> dict:
    """CONFIG_SCHEMA entries for the six pushed keys (rule 1). The defaults
    are NOT TOLD, so an effect that splices these in renders exactly as it
    does today until SpotFX writes something."""
    return {
        vol.Optional(
            SHAPE_KEY,
            description="Word shape: the shape's id (driven by SpotFX; "
                        "empty = none)",
            default="",
        ): str,
        vol.Optional(
            SEQ_KEY,
            description="Word shape: a counter per shape event, so two of "
                        "the same shape both edge (driven by SpotFX)",
            default=0,
        ): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(
            FORM_KEY,
            description="Word shape: seconds to form it, completing on the "
                        "word (driven by SpotFX)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=MAX_SECONDS)),
        vol.Optional(
            HOLD_KEY,
            description="Word shape: seconds it stands complete (driven by "
                        "SpotFX)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=MAX_SECONDS)),
        vol.Optional(
            RELEASE_KEY,
            description="Word shape: seconds to let it go (driven by "
                        "SpotFX)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=MAX_SECONDS)),
        vol.Optional(
            LEVEL_KEY,
            description="Word shape: the word's Energy, 0..1, for size and "
                        "count (driven by SpotFX; 0 = not told)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
    }


def _clamp_s(value) -> float:
    try:
        return min(MAX_SECONDS, max(0.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def told(config: Mapping) -> Optional[WordShapeTold]:
    """What this write told, or None when it told no shape (rule 3): no
    key, an empty id, an id this library does not know, or a form, hold and
    release that are all zero (nothing to run).

    The times come back clamped and the level floored, so a reader never
    has to defend itself against a bad number."""
    shape = str(config.get(SHAPE_KEY, "") or "")
    if not shape or not word_shapes.has(shape):
        return None
    form_s = _clamp_s(config.get(FORM_KEY))
    hold_s = _clamp_s(config.get(HOLD_KEY))
    release_s = _clamp_s(config.get(RELEASE_KEY))
    if form_s <= 0.0 and hold_s <= 0.0 and release_s <= 0.0:
        return None
    level = min(1.0, max(0.0, _clamp_s(config.get(LEVEL_KEY))))
    return WordShapeTold(shape=shape, seq=_int(config.get(SEQ_KEY)),
                         form_s=form_s, hold_s=hold_s, release_s=release_s,
                         level=level)


def _smoothstep(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def envelope(t, form: float, hold: float, release: float):
    """How far the shape is formed at `t` seconds from the first frame it
    moves: 0 -> 1 over `form` on a smoothstep, 1 through `hold`, 1 -> 0 over
    `release` on a smoothstep, and 0 once the release is over (and for any
    t < 0). Returns a float for a scalar `t`, an array for an array.

    A zero-length form or release is a step at its own edge rather than a
    division by zero: told form 0, the shape is already complete at t = 0.
    """
    form = max(0.0, float(form or 0.0))
    hold = max(0.0, float(hold or 0.0))
    release = max(0.0, float(release or 0.0))
    scalar = np.isscalar(t) or (isinstance(t, np.ndarray) and t.ndim == 0)
    tt = np.asarray(t, dtype=np.float64)

    rising = _smoothstep(tt / form) if form > 0.0 else np.ones_like(tt)
    falling = (1.0 - _smoothstep((tt - form - hold) / release)
               if release > 0.0 else np.zeros_like(tt))

    out = np.where(tt < 0.0, 0.0,
                   np.where(tt < form, rising,
                            np.where(tt <= form + hold, 1.0,
                                     np.where(tt <= form + hold + release,
                                              falling, 0.0))))
    return float(out) if scalar else out


def release_s_for(form_s: float,
                  ratio: float = DEFAULT_RELEASE_RATIO) -> float:
    """The plan's default release — `ratio` times the form (section 2.4's
    `word_shape_release_ratio`). SpotFX owns the setting; this is the one
    place the default lives so nothing re-derives 1.5 by hand."""
    return _clamp_s(max(0.0, float(form_s or 0.0)) * max(0.0, float(ratio)))


__all__ = [
    "SHAPE_KEY", "SEQ_KEY", "FORM_KEY", "HOLD_KEY", "RELEASE_KEY",
    "LEVEL_KEY", "KEYS", "NOT_TOLD", "LEVEL_FLOOR", "MAX_SECONDS",
    "DEFAULT_FORM_S", "DEFAULT_HOLD_S", "DEFAULT_RELEASE_RATIO",
    "WordShapeTold", "envelope", "keys_for", "release_s_for",
    "schema_fields", "told",
]
