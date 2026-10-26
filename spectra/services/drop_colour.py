"""EVERY DROP ARRIVES IN A NEW COLOUR SET — the pick (predrop plan step 2,
/home/javi/fleet-spotfx/data/predrop-plan/report.md section 2).

The Admiral, 2026-10-25: "frequently we don't get a color change on the
drop. I want it to change color cleanly so the drop comes in a new color
set ... It should be a big color change, but it can vary, just close to 180
degrees." Amended at approval, 2026-10-26: "if we have a pre-drop, fade the
color throught the predrop, not an instant change. drops without them
should have an instant change."

This module is THE PICK and nothing else: pure, no I/O, no clock, so the
rule is testable over his real sets (tests/fixtures/drop_colour_his_sets.
json). Where the pick lands, what holds it and how the fade runs are
ResponseEngine.drop_color_change (scene_response.py) and the trigger
clock's drop path (trigger_engine.py, "THE DROP COLOUR CHANGE").

THE RULE, in the order it decides:

  - THE REFERENCE is what the room is SHOWING: the room's live wheel
    position (the colour journey rotates the active set's palette to it,
    so that is the hue on the lights), or nothing when a RAINBOW is showing
    (a rainbow has no single hue). The caller resolves it.
  - THE BAND is every single-hue set within `spread_deg` of the opposite
    point: 150-210 degrees away at the default 30, i.e. a circular
    distance of at least 180 - spread. Measured as the colour journey
    measures (color_wheel.wheel_position: the weighted mean hue of a set's
    colours; selection_kernel.wheel_travel_deg: the shorter arc).
  - RAINBOWS COUNT AS BIG: from a single hue, a rainbow is as big a change
    as the band (his "it can vary"); from a rainbow, every single-hue set
    is. A rainbow to another rainbow only when the pool holds nothing
    else (RUNG_RAINBOW_ONLY). A set with no hue at all (his brightness
    sets) is never picked: it changes no colour.
  - THE DRAW is weighted: his own selector weight for each set (curve x
    genre x group — the caller computes it, as every colour pick does)
    TIMES its closeness to the opposite point, so the sets nearest 180
    degrees are likeliest and the change still varies from drop to drop.
    Closeness runs linearly from EDGE_WEIGHT at the band's edge to 1.0 at
    exactly 180; a rainbow takes the neutral 1.0 (the journey's own
    rainbow exemption). A set his OWN curve vetoes here never reaches this
    module (the caller drops it, zero is a veto); a band whose weights are
    all zero for another reason (a genre or group zero, which the
    selector's own ladder relaxes) is drawn by closeness alone and says so
    (`relaxed`).
  - NOTHING IN THE BAND: the single-hue set farthest from the reference,
    named (RUNG_WIDEST). No other set at all: the current colours stay,
    named (RUNG_KEPT). Never silent.

Rungs, as the show log and the Review page name them: RUNG_BAND,
RUNG_TO_RAINBOW, RUNG_FROM_RAINBOW, RUNG_NO_HUE_YET, RUNG_RAINBOW_ONLY,
RUNG_WIDEST, RUNG_KEPT.
"""
from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Iterable, Optional

from spectra.services.selection_kernel import wheel_travel_deg

HALF_TURN_DEG = 180.0
# RoomControlState.drop_colour_spread_deg's default and bounds, stated here
# too so the pick never divides by a zero band or reaches past a half turn.
DEFAULT_SPREAD_DEG = 30.0
MIN_SPREAD_DEG = 5.0
MAX_SPREAD_DEG = 90.0
# How likely a set sitting exactly ON the band's edge is, against one dead
# opposite (1.0): a quarter. Low enough that "the ones nearest 180 degrees
# likeliest" holds, high enough that the edge still gets picked and the
# change varies (his "it can vary").
EDGE_WEIGHT = 0.25
_EPS = 1e-9

RUNG_BAND = "band"                    # a single hue 150-210 degrees away
RUNG_TO_RAINBOW = "to_rainbow"        # single hue -> a rainbow (counts as big)
RUNG_FROM_RAINBOW = "from_rainbow"    # a rainbow was showing -> a single hue
RUNG_NO_HUE_YET = "no_hue_yet"        # no hue known yet -> a single hue
RUNG_RAINBOW_ONLY = "rainbow_only"    # rainbow -> rainbow: nothing else eligible
RUNG_WIDEST = "widest_available"      # nothing in the band: the farthest set
RUNG_KEPT = "kept_current"            # no other set at all: colours stay


@dataclass(frozen=True)
class Option:
    """One eligible colour set, as the pick sees it."""
    set_id: str
    position_deg: Optional[float]   # wheel position; None = a rainbow or no hue
    rainbow: bool = False
    weight: float = 1.0             # his selector's weight here (curve x genre x group)


@dataclass(frozen=True)
class Pick:
    """The outcome. set_id None means the current colours stay (RUNG_KEPT).
    distance_deg is the arc from the reference to the picked set, None
    when either side has no single hue."""
    set_id: Optional[str]
    rung: str
    distance_deg: Optional[float] = None
    in_band: bool = False
    band_size: int = 0
    relaxed: bool = False
    spread_deg: float = DEFAULT_SPREAD_DEG

    def as_dict(self) -> dict:
        return {"set_id": self.set_id, "rung": self.rung,
                "distance_deg": (round(self.distance_deg, 1)
                                 if self.distance_deg is not None else None),
                "in_band": self.in_band, "band_size": self.band_size,
                "relaxed": self.relaxed, "spread_deg": self.spread_deg}


def clamp_spread(spread_deg: float) -> float:
    return max(MIN_SPREAD_DEG, min(MAX_SPREAD_DEG, float(spread_deg)))


def in_band(distance_deg: float, spread_deg: float) -> bool:
    """A circular distance (0-180) inside the band around the opposite point."""
    return distance_deg >= HALF_TURN_DEG - clamp_spread(spread_deg) - _EPS


def closeness(distance_deg: float, spread_deg: float) -> float:
    """EDGE_WEIGHT on the band's edge, 1.0 at exactly 180 degrees, linear
    between (clamped, so a caller passing an out-of-band distance gets the
    edge weight, never a negative one)."""
    spread = clamp_spread(spread_deg)
    t = (distance_deg - (HALF_TURN_DEG - spread)) / spread
    t = max(0.0, min(1.0, t))
    return EDGE_WEIGHT + (1.0 - EDGE_WEIGHT) * t


def _draw(weighted: list[tuple[Option, float]], rng: Random) -> tuple[Option, bool]:
    """A proportional draw over (option, score), sorted by set id first so a
    seeded rng is reproducible whatever order the pool arrived in. When
    every score is zero the draw is uniform and says so (relaxed=True)."""
    ordered = sorted(weighted, key=lambda pair: pair[0].set_id)
    total = sum(max(0.0, s) for _o, s in ordered)
    relaxed = total <= 0.0
    if relaxed:
        ordered = [(o, 1.0) for o, _s in ordered]
        total = float(len(ordered))
    r = rng.random() * total
    acc = 0.0
    for option, score in ordered:
        acc += max(0.0, score)
        if r < acc:
            return option, relaxed
    return ordered[-1][0], relaxed


def pick(current_id: Optional[str], current_deg: Optional[float],
         options: Iterable[Option], *, spread_deg: float = DEFAULT_SPREAD_DEG,
         rng: Random, current_rainbow: bool = False) -> Pick:
    """The drop's new colour set (the module docstring's rule).

    `current_id` is the set showing (never picked again); `current_deg` the
    reference hue (None when a rainbow is showing, `current_rainbow` True,
    or no hue is known yet); `options` the eligible pool with each set's
    own weight."""
    spread = clamp_spread(spread_deg)
    others = [o for o in options if o.set_id != current_id]
    chromatic = [o for o in others if o.position_deg is not None]
    rainbows = [o for o in others if o.position_deg is None and o.rainbow]
    if not chromatic and not rainbows:
        return Pick(None, RUNG_KEPT, spread_deg=spread)

    if current_deg is None:
        # Nothing single-hued is showing: every single hue is a big change.
        if chromatic:
            winner, relaxed = _draw([(o, o.weight) for o in chromatic], rng)
            rung = RUNG_FROM_RAINBOW if current_rainbow else RUNG_NO_HUE_YET
            return Pick(winner.set_id, rung, in_band=True,
                        band_size=len(chromatic), relaxed=relaxed,
                        spread_deg=spread)
        winner, relaxed = _draw([(o, o.weight) for o in rainbows], rng)
        return Pick(winner.set_id, RUNG_RAINBOW_ONLY, in_band=False,
                    band_size=0, relaxed=relaxed, spread_deg=spread)

    distances = {o.set_id: wheel_travel_deg(current_deg, o.position_deg)
                 for o in chromatic}
    band = [o for o in chromatic if in_band(distances[o.set_id], spread)]
    weighted = ([(o, o.weight * closeness(distances[o.set_id], spread))
                 for o in band]
                + [(o, o.weight) for o in rainbows])
    if weighted:
        winner, relaxed = _draw(weighted, rng)
        if winner.rainbow and winner.position_deg is None:
            return Pick(winner.set_id, RUNG_TO_RAINBOW, in_band=True,
                        band_size=len(weighted), relaxed=relaxed,
                        spread_deg=spread)
        return Pick(winner.set_id, RUNG_BAND,
                    distance_deg=distances[winner.set_id], in_band=True,
                    band_size=len(weighted), relaxed=relaxed,
                    spread_deg=spread)

    # Nothing in the band (only reachable with single-hue options left):
    # the farthest one, ties drawn by weight.
    farthest = max(distances[o.set_id] for o in chromatic)
    tied = [o for o in chromatic if distances[o.set_id] >= farthest - _EPS]
    winner, relaxed = _draw([(o, o.weight) for o in tied], rng)
    return Pick(winner.set_id, RUNG_WIDEST,
                distance_deg=distances[winner.set_id], in_band=False,
                band_size=0, relaxed=relaxed, spread_deg=spread)
