"""PATTERN LIGHT — light EXACTLY the pixels named by a bitmask, black
everywhere else. SpotFX-authored; not fork code.

WHY IT EXISTS, and it is one job only: the commissioning ground-truth test
(`spectra/services/commissioning.py`) addresses a whole composition of
pixels in GRAY-CODE patterns, so that ~22 captures identify every pixel's
camera position at once instead of 736 one-at-a-time captures. A gray-code
pattern is not a contiguous run, so the range lamp (`pixelRange.py`, its
sibling instrument) cannot express one.

THE EFFECT IS A DUMB LAMP AND STAYS ONE. It knows nothing about gray code,
about bits, or about what the pattern means — it lights the pixels it is
handed. Everything about the CODE lives in `spectra/services/gray_code.py`,
which is pure and offline-provable; if the decoder and the lamp both knew
the code, a change to one could silently disagree with the other. So the
wire carries the mask itself: `pattern`, one character per effect pixel,
'1' lit and '0' dark, index-aligned to the virtual's own effect buffer.
That is a few hundred bytes for his whole TV wrap — cheaper than the
argument about who owns the arithmetic.

THE PATTERN IS AN ADDRESSING FACT, NOT A POSITION, exactly as
`pixelRange.py`'s range is: indices into the virtual's own effect pixel
buffer, the same index space every other effect renders into and the same
space `fx/virtual_gain_mask.py`'s mask is indexed by. This effect holds no
opinion about where those pixels physically are, and neither does anything
built from what it lights (`spectra/models/room_map.py`).

REGISTRY-EXEMPT, deliberately, for the same reason `pixelRange` is: this is
a MEASURING INSTRUMENT, not something to author a scene with. It is absent
from `config/effect_params.json`, so it never appears on the Initial Set
tab, in a band patch, in Sonic's parameter catalogue, or in a colour set's
accept list.

A pattern SHORTER than the virtual leaves the remaining pixels dark; a
longer one is truncated. Both are stated here rather than guessed at: a
capture that photographs the wrong pixels is worse than one that lights
fewer than asked, which the decode reports by name as pixels it never saw.
"""
import numpy as np
import voluptuous as vol

from fx.color import parse_color, validate_color
from fx.effects.temporal import TemporalEffect


def validate_pattern(value):
    """A bitmask string: '0' and '1' only. Anything else is a wire error,
    not something to interpret — an unrecognised character would silently
    become "dark" and the decode would blame the fixture."""
    text = str(value)
    if text and set(text) - {"0", "1"}:
        raise vol.Invalid("pattern must contain only '0' and '1'")
    return text


class PixelPatternEffect(TemporalEffect):
    NAME = "Pixel Pattern"
    CATEGORY = "Non-Reactive"
    # Absent from config/effect_params.json on purpose — see the module
    # docstring, and `pixelRange.py`'s, for the same discipline.

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "color", description="Colour of the lit pixels", default="#FFFFFF"
            ): validate_color,
            vol.Optional(
                "pattern",
                description="One character per effect pixel: '1' lit, '0' dark",
                default="",
            ): validate_pattern,
        },
    )

    def config_updated(self, config):
        self.color = np.array(parse_color(self._config["color"]), dtype=float)
        self._pattern = str(self._config["pattern"])

    def on_activate(self, pixel_count):
        # THE FIRST FRAME IS ALREADY CORRECT, deliberately: a temporal
        # effect's loop runs on its own thread, so a frame assembled between
        # activation and the first tick would come out black — and a capture
        # that photographs black while believing it photographed a pattern
        # is the one failure this whole instrument exists to make
        # impossible. Rendering here costs one array and removes the race.
        self.pixels = self._paint(pixel_count)

    def _paint(self, pixel_count: int):
        out = np.zeros((pixel_count, 3), dtype=float)
        mask = np.frombuffer(self._pattern.encode("ascii"), dtype=np.uint8)
        mask = mask[:pixel_count] == ord("1")
        if mask.any():
            out[: mask.size][mask] = self.color
        return out

    def effect_loop(self):
        self.pixels = self._paint(self.pixel_count)
