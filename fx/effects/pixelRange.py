"""RANGE LIGHT — white (or any colour) over a configured pixel range of one
virtual, black everywhere else. SpotFX-authored; not fork code.

WHY IT EXISTS, and it is one job only: the room light-field mapping run has
to be able to light ONE SEGMENT of a device on its own so a camera can see
where THAT segment's light lands. The run's whole-device step already had a
write primitive (`singleColor` at full white); this is that primitive with a
range, so a per-segment capture is the same protocol with a narrower lamp
rather than a second protocol.

REGISTRY-EXEMT, deliberately, and for the same reason the phase keys and
`burst_rockets` are (fx/device_model.py's own notes): this effect is a
MEASURING INSTRUMENT, not something to author a scene with. It is absent
from `config/effect_params.json`, so it never appears on the Initial Set
tab, in a band patch, in Sonic's parameter catalogue, or in a colour set's
accept list. It rides ONLY the dedicated mapping write
(spectra/services/room_mapping.py).

THE RANGE IS AN ADDRESSING FACT, NOT A POSITION. `range_start`/`range_end`
are inclusive indices into the virtual's own effect pixel buffer — the same
index space every other effect renders into, and the same space
`fx/virtual_gain_mask.py`'s mask is indexed by. This effect holds no
opinion about where those pixels physically are, and neither does the map
that is built from what it lights (spectra/models/room_map.py).

An out-of-range or inverted pair lights NOTHING rather than guessing: a
capture that photographs the wrong pixels is worse than one that reports
"this emitter added no measurable light", which the run already says by
name.
"""
import numpy as np
import voluptuous as vol

from fx.color import parse_color, validate_color
from fx.effects.temporal import TemporalEffect


class PixelRangeEffect(TemporalEffect):
    NAME = "Pixel Range"
    CATEGORY = "Non-Reactive"
    # Absent from config/effect_params.json on purpose — see the module
    # docstring: SPECTRA's own surfaces (Initial Set, band patches, Sonic's
    # catalogue, colour-set accept lists) all enumerate that registry, so
    # leaving it out is what keeps this instrument off every one of them.

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "color", description="Colour of the lit range", default="#FFFFFF"
            ): validate_color,
            vol.Optional(
                "range_start",
                description="First lit pixel (inclusive)",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Optional(
                "range_end",
                description="Last lit pixel (inclusive); -1 means to the end",
                default=-1,
            ): vol.All(vol.Coerce(int), vol.Range(min=-1)),
        },
    )

    def config_updated(self, config):
        self.color = np.array(parse_color(self._config["color"]), dtype=float)
        self.range_start = int(self._config["range_start"])
        self.range_end = int(self._config["range_end"])

    def on_activate(self, pixel_count):
        pass

    def effect_loop(self):
        out = np.zeros((self.pixel_count, 3), dtype=float)
        start = self.range_start
        end = self.pixel_count - 1 if self.range_end < 0 else self.range_end
        start = max(0, start)
        end = min(self.pixel_count - 1, end)
        if start <= end:
            out[start : end + 1] = self.color
        self.pixels = out
