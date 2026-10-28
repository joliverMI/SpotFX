"""THE DROP COLOUR RE-SAMPLE — told whether a colour change landed on this
drop, so Star's thrown-back pieces wear it.

Built 2026-10-28, widening predrop plan 2.2/2.3/3.5's own rule (Star's
pieces re-sample their palette positions from the live colour set — see
fx/effects/radial.py's `_begin_snap`/`_drop_snap`, and the plan's own "Star
re-samples its palette as the colour fades") past the pre-drop fade it
shipped scoped to. Asked whether a drop with no pre-drop should also
change Star's colour, the Admiral answered (2026-10-28): "yes, the star
should change color."

A drop with a pre-drop fades its colour change across it, and Star already
knows this happened (`_pd_seen`, set when its own pre-drop clock plays) —
that is untouched by this module. A drop with NO pre-drop changes colour
INSTANTLY, right before this drop's own phase arm lands
(spectra/services/drop_colour.py is the pick; ResponseEngine.
drop_color_change / _color_jump lands it; TriggerEngine._fire orders the
colour change ahead of the drop's own response). Star has no pre-drop
clock to read in that case, so SpotFX has to say so directly.

THE KEY, ON EVERY DROP ARM, to every virtual in `fx.device_model.
DROP_COLOUR_RESAMPLE_EFFECTS` (radial only — no other effect re-samples a
palette position this way): `drop_color_landed` (bool — the fx schema
naming check refuses a British "colour" in a key, so the KEY ITSELF is
`drop_color_landed` even though this module, like `drop_colour.py`, is
named in his own spelling) — True exactly when a colour change landed on
THIS drop. The value is
`ResponseEngine.on_event`'s own `_take_drop_colour_claim()` (the SAME
claim that already tells a drop's band to skip its own colour-jump kind,
so one drop makes one change) — never a second idea of "did it change".
A held colour change (preview, Force Colour, house mode, an active 2D
gradient) or a drop with nothing to pick from never claims, so this reads
False and the pieces keep whatever colour they fell into the core with.

THREE RULES (lull_dark.py's, kept identical):

1. KEYS RIDE ONLY THE DEDICATED DROP ARM WRITE — never config/
   effect_params.json, never an editor surface or a band patch.
2. EVERY MEMBER GETS THE KEY ON EVERY DROP ARM, even False. A claim from
   an earlier drop must never be read as still standing on this one.
3. NOT TOLD (an older SpotFX, a hand test, a LedFX UI scrub) is False —
   the effect's own stored colours, exactly as before this key existed.
"""

from __future__ import annotations

from typing import Mapping

import voluptuous as vol

KEY = "drop_color_landed"


def key_for(landed: bool) -> dict:
    """The one key SpotFX pushes on a drop arm (module docstring)."""
    return {KEY: bool(landed)}


def schema_field() -> dict:
    """CONFIG_SCHEMA entry for the key (rule 1)."""
    return {
        vol.Optional(
            KEY,
            description="Drop: a colour change landed on this drop "
                        "(driven by SpotFX)",
            default=False,
        ): bool,
    }


def landed(config: Mapping) -> bool:
    """Was this drop told a colour change landed on it (rule 3: not told
    is False)."""
    return bool(config.get(KEY, False))
