"""THE LULL HAND-OFF HOOK — how a lull is TOLD what to leave for the drop.

Built 2026-10-08 (fish-lull plan, phase 1; the Admiral approved it with
"i like the updated plan for the fish lull searcher ... make sure they work
together on the fish fireworks stuff"). It is the ONE shared interface
between an effect's own lull/drop choreography and the SpotFX side that
knows what the drop will be — the fish's searching keeper is its first
user, and the drop-scene-variety work (drop-led scene switching, the
fireworks melds) plugs into it by supplying a RESOLVER, never by building a
second way to tell a lull anything.

It is a sibling of fx/effects/lull_dark.py on purpose and follows its three
rules, because that module already solved the only hard problem: an effect
only ever sees `phase` and `phase_progress`, so anything else it needs to
know about a lull has to ride the lull's own ARM WRITE from SpotFX
(spectra/services/scene_response._drive_phase, the one place a phase is
written).

THE KEYS

On every LULL arm, to every virtual whose effect is in
`fx.device_model.LULL_HANDOFF_EFFECTS`:

- `lull_keep` (int, 0..MAX_KEEP): how many pieces (fish, blobs, chains) the
  lull leaves on the panel at its HALF-WAY MARK and holds until the drop.
  0 = leave nothing — for the fish, exactly its pre-hook lull (everything
  gone by a third, dark after two thirds). An effect clamps to what it can
  hold and may spawn the shortfall.
- `lull_next` (str): the registry name of the effect the DROP will land on
  this virtual ("fireworks", "radial", ...); "" = the same effect, or
  unknown. INFORMATIONAL: an effect may shape its hold for the arrival
  (the fish spaces its keepers further apart so an adopting effect gets
  distinct origins) but must render correctly ignoring it.
- `lull_s` (float s): the lull's REAL length, the gap to its own drop, so
  "half way" is a moment on the effect's own phase clock. 0 = not told.

On every DROP arm, to every virtual in `fx.device_model.
DROP_INTENSITY_EFFECTS`:

- `drop_intensity` (float 0..1): the fire's render intensity, so a drop's
  length and speed can scale with the music (`drop_scale`, below). 0 = not
  told: the effect's fixed legacy drop. SpotFX never pushes a true 0 — it
  floors a told intensity at DROP_INTENSITY_FLOOR — so 0 only ever means
  "not told".

THREE RULES (lull_dark.py's, kept identical so there is one way an effect
is told anything about a phase):

1. KEYS RIDE ONLY THE DEDICATED PHASE WRITE. Never in config/
   effect_params.json, never on an editor surface or a band patch. An
   adopter splices `**schema_fields()` (and `**drop_schema_fields()`) into
   its CONFIG_SCHEMA and `*KEYS` (`DROP_KEY`) into ADVANCED_KEYS so a
   validated write keeps them.
2. EVERY MEMBER GETS EVERY KEY ON EVERY ARM, even at the default.
   `Effect._apply_config` partial-merges, so a `lull_keep: 3` pushed for one
   song would otherwise survive into the next lull; re-pushing the resolved
   value every time is what makes the previous lull's request forgettable.
3. NOT TOLD IS THE EFFECT'S OWN BEHAVIOUR. An older SpotFX, a hand test or a
   LedFX UI scrub pushes no keys; the effect then uses its schema defaults.

THE `keep == 0` DARK RULE. An effect that is a member of BOTH this set and
LULL_DARK_EFFECTS goes dark at its dark point only when it was told
`keep == 0`; told to keep pieces, it holds them instead. (No effect is in
both today; the fish never joins LULL_DARK_EFFECTS because its lull is
never dark unless told keep 0.)

WHO DECIDES (SpotFX): `scene_response.ResponseEngine` asks a RESOLVER —
`scene_response.install_lull_handoff_resolver(fn)` — what each lull should
be told; with none installed the default is `keep = DEFAULT_KEEP`, no next
effect, `lull_s = the gap`. See scene_response's "THE LULL HAND-OFF HOOK"
docstring section for the resolver contract.

HOW AN EFFECT OPTS IN (three steps, lull_dark's shape):
  1. splice the schema fields + ADVANCED_KEYS (rule 1);
  2. add its registry name to `fx.device_model.LULL_HANDOFF_EFFECTS` (and
     to DROP_INTENSITY_EFFECTS if its drop should scale);
  3. read `keep(config)` where it decides what survives its lull,
     `next_effect(config)` where it shapes the hold, `keep_mark(...)` for
     the half-way moment, and `drop_scale(drop_intensity(config), ...)` for
     the drop.
"""

from __future__ import annotations

from typing import Mapping, Optional

import voluptuous as vol

KEEP_KEY = "lull_keep"
NEXT_KEY = "lull_next"
LULL_S_KEY = "lull_s"
KEYS = (KEEP_KEY, NEXT_KEY, LULL_S_KEY)
DROP_KEY = "drop_intensity"

# The Admiral's "one is left at the half way mark".
DEFAULT_KEEP = 1
# the fish's own MAX_RUSH ceiling: more pieces than any lull effect holds
MAX_KEEP = 24

# Where the keep mark sits when the lull's length was NOT told: half of
# phase_progress. Progress ramps over ~90% of the gap and hangs, so this
# lands at ~45% of the wall clock — the honest best without the length.
LEGACY_KEEP_MARK = 0.5

# A told drop's intensity is never pushed below this, so 0 can only ever
# mean "not told" (rule 3) rather than also meaning "a silent drop".
DROP_INTENSITY_FLOOR = 0.01

# THE INTENSITY-SCALED DROP. The loudest AUTOMATIC intensity (spectra
# intensity_scale: HEADROOM_RESERVE 0.6 x SCALE_MAX 1.25) is exactly the
# legacy drop; a marked track at 1.0 runs DROP_SCALE_MAX of it; a quiet
# song shrinks toward the effect's own floor (`scale_min`).
DROP_AUTO_CEILING = 0.75
DROP_SCALE_MAX = 1.2
DEFAULT_DROP_SCALE_MIN = 0.4


def clamp_keep(n) -> int:
    try:
        return max(0, min(int(n), MAX_KEEP))
    except (TypeError, ValueError):
        return DEFAULT_KEEP


def keys_for(keep: int, next_effect: str, lull_s: float) -> dict:
    """The three config keys SpotFX pushes on a lull arm (module docstring)."""
    return {
        KEEP_KEY: clamp_keep(keep),
        NEXT_KEY: str(next_effect or ""),
        LULL_S_KEY: max(0.0, float(lull_s or 0.0)),
    }


def drop_keys_for(intensity: float) -> dict:
    """The one key SpotFX pushes on a drop arm — floored so it is TOLD."""
    i = min(1.0, max(DROP_INTENSITY_FLOOR, float(intensity or 0.0)))
    return {DROP_KEY: i}


def schema_fields() -> dict:
    """CONFIG_SCHEMA entries for the three lull keys (rule 1)."""
    return {
        vol.Optional(
            KEEP_KEY,
            description="Lull: pieces left on the panel at the half-way "
                        "mark (driven by SpotFX)",
            default=DEFAULT_KEEP,
        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_KEEP)),
        vol.Optional(
            NEXT_KEY,
            description="Lull: the effect the drop will land on (driven by "
                        "SpotFX; empty = same effect / unknown)",
            default="",
        ): str,
        vol.Optional(
            LULL_S_KEY,
            description="Lull: its real length in seconds (driven by "
                        "SpotFX; 0 = not told)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
    }


def drop_schema_fields() -> dict:
    """CONFIG_SCHEMA entry for the drop key (rule 1)."""
    return {
        vol.Optional(
            DROP_KEY,
            description="Drop: the fire's intensity (driven by SpotFX; "
                        "0 = not told, the fixed drop)",
            default=0.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
    }


def keep(config: Mapping) -> int:
    return clamp_keep(config.get(KEEP_KEY, DEFAULT_KEEP))


def next_effect(config: Mapping) -> str:
    return str(config.get(NEXT_KEY, "") or "")


def lull_s(config: Mapping) -> float:
    try:
        return max(0.0, float(config.get(LULL_S_KEY, 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def told(config: Mapping) -> bool:
    """SpotFX told this lull its real length (the keep mark is a moment in
    seconds), rather than the effect falling back to progress 0.5."""
    return lull_s(config) > 0.0


def keep_mark(config: Mapping, progress: float, phase_t: float,
              legacy_at: float = LEGACY_KEEP_MARK) -> float:
    """How far this lull is toward its half-way KEEP MARK: 0 at the lull's
    edge, 1 at the mark, past 1 after it. Told: seconds on the effect's own
    phase clock (`phase_t`) over half the lull. Not told: `progress` over
    `legacy_at` — the same seconds-are-the-clock rule lull_dark states."""
    if told(config):
        half = lull_s(config) / 2.0
        return max(0.0, float(phase_t)) / max(half, 1e-6)
    return max(0.0, float(progress)) / max(float(legacy_at), 1e-6)


def drop_intensity(config: Mapping) -> Optional[float]:
    """The told drop intensity, or None when not told (rule 3)."""
    try:
        v = float(config.get(DROP_KEY, 0.0) or 0.0)
    except (TypeError, ValueError):
        return None
    return v if v > 0.0 else None


def drop_scale(intensity: Optional[float],
               scale_min: float = DEFAULT_DROP_SCALE_MIN) -> Optional[float]:
    """How long and hard a drop runs, as a multiple of the legacy drop:
    `clamp(m + (1 - m) * I / DROP_AUTO_CEILING, m, DROP_SCALE_MAX)` with
    `m = scale_min` — so the automatic ceiling (0.75) is exactly the legacy
    drop and a marked track at 1.0 runs 20% longer. None when not told: the
    caller keeps its constants byte for byte."""
    if intensity is None:
        return None
    m = min(max(float(scale_min), 0.0), 1.0)
    s = m + (1.0 - m) * float(intensity) / DROP_AUTO_CEILING
    return min(max(s, m), DROP_SCALE_MAX)
