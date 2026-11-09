"""What a colour is called when someone sings it — the seed for the sung
labels on a colour set (lyrics plan step 3; his ruling: "add smarter color
labels than just the names").

PURE. A palette and a card name in, words out: no file, no model, nothing to
wait on. It runs on every read of the label list, so a set whose colours he
changes gets the right words without anything being re-seeded.

THE LABELS ARE WORDS PEOPLE SING. Each hue family carries its name, in English
and Spanish (his library is about half Latin), its other names (crimson,
sapphire), and the few things it brings to mind (blood, ocean). Claude's drafted
meanings for a particular set (spectra/services/color_meanings.py) add to these
and he corrects both on the Sung labels page.

A CARD'S NAME ADDS WHAT ITS COLOURS CANNOT. "Mid - Ice" and "Blood Red" tell you
something the gradient does not. His card names follow "<group> - <meaning>"
with colour words and bookkeeping words mixed in, so colour words are dropped
(the palette already gave them) and so are the words that name a family of sets
rather than a meaning (STOP_WORDS).
"""
from __future__ import annotations

import colorsys
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from spectra.models.gradient2d import parse_stops

# Below this much saturation or brightness a colour has no hue worth naming.
_BLACK_VALUE = 0.12
_GREY_SATURATION = 0.14
_WHITE_VALUE = 0.72
# Darker or paler than these reads as a different word (navy, sky blue).
_DARK_VALUE = 0.5
_PALE_SATURATION = 0.45

# A card this many hue families wide is a rainbow, whatever it is called.
_RAINBOW_FAMILIES = 5
# Words from at most this many families, or a busy gradient's label list drowns
# out what it is mostly about.
MAX_FAMILIES = 3


@dataclass(frozen=True)
class Family:
    names: tuple[str, ...]
    shades: tuple[str, ...] = ()
    dark: tuple[str, ...] = ()
    pale: tuple[str, ...] = ()
    things: tuple[str, ...] = ()

    def words(self, *, dark: bool, pale: bool) -> list[str]:
        out = [*self.names, *self.shades]
        if dark:
            out += self.dark
        if pale:
            out += self.pale
        return out + list(self.things)


FAMILIES: dict[str, Family] = {
    "red": Family(("red", "rojo"), ("crimson", "scarlet", "ruby", "cherry"),
                  dark=("burgundy", "maroon"), things=("blood", "fire", "rose", "heart")),
    "orange": Family(("orange", "naranja"), ("tangerine", "amber"),
                     dark=("rust",), things=("sunset", "ember", "flame", "autumn")),
    "yellow": Family(("yellow", "amarillo"), ("gold", "golden", "dorado", "lemon"),
                     things=("sun", "sunshine", "honey")),
    "green": Family(("green", "verde"), ("emerald", "lime", "jade"),
                    dark=("forest",), things=("grass", "leaf", "jungle", "money")),
    "cyan": Family(("cyan", "turquoise", "turquesa", "teal", "aqua"),
                   things=("ice", "lagoon", "glacier", "pool")),
    "blue": Family(("blue", "azul"), ("sapphire", "cobalt", "azure"),
                   dark=("navy", "midnight"), pale=("sky blue", "baby blue"),
                   things=("ocean", "sea", "sky", "rain", "water")),
    "purple": Family(("purple", "morado", "violet", "violeta"),
                     ("amethyst", "indigo", "plum"), pale=("lavender", "lilac"),
                     things=("royal", "grape", "twilight")),
    "pink": Family(("pink", "rosa", "magenta", "fuchsia"), ("blush",),
                   things=("flamingo", "bubblegum", "candy")),
    "white": Family(("white", "blanco"), ("ivory", "pearl", "silver", "plata"),
                    things=("snow", "moon", "cloud", "ghost")),
    "grey": Family(("grey", "gray", "gris"), ("ash", "silver"), things=("smoke", "fog")),
    "black": Family(("black", "negro"), ("ebony", "onyx"),
                    things=("night", "shadow", "darkness")),
}

RAINBOW_WORDS = ("rainbow", "arcoiris")

# Words in his card names that say which family of sets a card belongs to or
# how it is used, not what it means.
STOP_WORDS = frozenset({
    "mid", "power", "line", "lines", "orbit", "orbits", "base", "group", "groups",
    "first", "setting", "settings", "brightness", "bright", "dim", "bass", "drop",
    "with", "and", "the", "of", "a", "an", "set", "color", "colour", "colors", "colours",
    "new", "all", "black hole", "black holes",
})

_COLOUR_WORDS = frozenset(
    w for fam in FAMILIES.values() for w in (*fam.names, *fam.shades, *fam.dark, *fam.pale)
    if " " not in w
) | frozenset(RAINBOW_WORDS)

_STOP_PHRASES = tuple(w for w in STOP_WORDS if " " in w)

# A phrase longer than this out of a card's name is a title, not a sung word.
_MAX_NAME_WORDS = 3


def word_key(text: str) -> str:
    """The form two words are compared in: lower case, no accents, no
    apostrophes, other punctuation as a space. "Azúl!" and "azul" are one
    label, and "don't" matches a timeline word normalised to "dont"."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    no_apostrophes = re.sub(r"['’`]", "", no_accents.casefold())
    return " ".join(re.sub(r"[\W_]", " ", no_apostrophes).split())


def family_of(hex_colour: str) -> tuple[Optional[str], bool, bool]:
    """(family, is_dark, is_pale) for one "#rrggbb"; (None, ...) if unparseable."""
    try:
        r, g, b = (int(hex_colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    except (ValueError, IndexError, TypeError):
        return None, False, False
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if v < _BLACK_VALUE:
        return "black", True, False
    if s < _GREY_SATURATION:
        return ("white" if v >= _WHITE_VALUE else "grey"), v < _DARK_VALUE, False
    degrees = h * 360.0
    if degrees < 12 or degrees >= 345:
        family = "red"
    elif degrees < 42:
        family = "orange"
    elif degrees < 70:
        family = "yellow"
    elif degrees < 165:
        family = "green"
    elif degrees < 200:
        family = "cyan"
    elif degrees < 255:
        family = "blue"
    elif degrees < 295:
        family = "purple"
    else:
        family = "pink"
    return family, v < _DARK_VALUE, s < _PALE_SATURATION


def palette_of(entries: Iterable) -> list[str]:
    """Every foreground colour stop of a card's entries, in order. Accepts
    the projection's entry objects. A set's background is left out: 30 of
    his entries author a black background that says nothing about the set."""
    out: list[str] = []
    for entry in entries:
        value = getattr(entry, "color_value", None)
        out += [hex_colour for _, hex_colour in parse_stops(value)]
    return out


def _colour_words(palette: Sequence[str], is_rainbow: bool, is_pool: bool) -> list[str]:
    tally: Counter[str] = Counter()
    dark: Counter[str] = Counter()
    pale: Counter[str] = Counter()
    for hex_colour in palette:
        family, is_dark, is_pale = family_of(hex_colour)
        if family is None:
            continue
        tally[family] += 1
        dark[family] += int(is_dark)
        pale[family] += int(is_pale)
    # Black between the stops of a coloured gradient is the shape of the
    # effect, not a colour of the set ("Line - Red" is a red line on black).
    if len(tally) > 1:
        tally.pop("black", None)
    if is_rainbow or (len(tally) >= _RAINBOW_FAMILIES and not is_pool):
        return list(RAINBOW_WORDS)
    # A group of seven one-colour sets is a pool, not a seven-colour palette;
    # three of its colours picked by tally would describe nothing about it.
    if is_pool and len(tally) > MAX_FAMILIES:
        return []
    out: list[str] = []
    for family, count in tally.most_common(MAX_FAMILIES):
        out += FAMILIES[family].words(dark=dark[family] * 2 > count,
                                      pale=pale[family] * 2 > count)
    return out


def _name_words(name: str) -> list[str]:
    """What the card's name says beyond its bookkeeping: any colour it names
    outright, whatever the gradient happens to be, and the rest of the name as
    one phrase ("Puerto Rico Red" -> "red", "puerto rico")."""
    colours: list[str] = []
    phrases: list[str] = []
    for segment in re.split(r"\s+-\s+", name or ""):
        key = word_key(segment)
        for phrase in _STOP_PHRASES:
            key = f" {key} ".replace(f" {phrase} ", " ").strip()
        kept: list[str] = []
        for word in key.split():
            if word in _COLOUR_WORDS:
                colours.append(word)
            elif word not in STOP_WORDS and not word.isdigit():
                kept.append(word)
        if kept and len(kept) <= _MAX_NAME_WORDS:
            phrases.append(" ".join(kept))
    return [*phrases, *colours]


def is_colour_word(word: str) -> bool:
    """A genuine colour/shade name (red, azul, sapphire, navy, rainbow...),
    the one kind of word that may honestly belong to a whole family of sets
    sharing that hue rather than telling them apart."""
    return word_key(word) in _COLOUR_WORDS


def dedupe(words: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for word in words:
        key = word_key(word)
        if key and key not in seen:
            seen.add(key)
            out.append(word)
    return out


def seed_labels(name: str, palette: Sequence[str], *, is_rainbow: bool = False,
                is_pool: bool = False) -> list[str]:
    """The labels a colour set starts with, before he or Claude add any.
    `is_pool`: a Group, whose palette is the union of its members'."""
    return dedupe([*_name_words(name), *_colour_words(palette, is_rainbow, is_pool)])
