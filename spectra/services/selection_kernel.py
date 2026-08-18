"""SPECTRA selection kernel — pure functions, no I/O, no engine state.

Decision-complete (decisions 1+2, data/spectra-sequencing-design/
decision-five-answers.md): per candidate

    score = curve(intensity) × genre_mult × affinity_mult

then a weighted random draw proportional to scores. Zero is a HARD VETO —
a candidate scoring 0 (curve at zero there, or a zero multiplier) cannot
fire. The current scene is excluded from the draw ("stay" is dwell's job,
not a sampled outcome). When everything scores zero, a deterministic
fallback ladder relaxes one constraint per rung:

    full → drop affinity → drop genre → re-admit current (curve-weighted)
         → uniform among curve-eligible → terminal

The terminal rung is per selector kind: scenes STAY on the current scene,
flares fire NOTHING. The uniform rung keeps only the curve's zero-veto as an
eligibility gate and discards score magnitude — the guaranteed-termination
rung when weighted drawing is impossible (all earlier rungs demand a
positive, finite score; a pathological curve height like inf falls through
to uniform rather than poisoning the draw).

The colour-set selector is the kernel's third flavour (decision 3, wired
last): score = curve(intensity) × genre × WHEEL-TRAVEL × GROUP, where wheel
travel is a likelihood curve over the angular distance (0–180°) the pick
would move the room's current wheel position, and GROUP is described next.
Its ladder is its own:

    full → drop group curves → drop wheel-travel → drop genre
         → uniform among curve-eligible → terminal KEEP the current colours

Colours are never forced to churn: when nothing else is eligible the room
keeps its palette. Rainbow-tagged sets (chromatic span > 180°,
services/color_wheel.py) take a NEUTRAL ×1.0 wheel factor and are skipped
by rotation mechanics — they stay eligible through their intensity curves.

**Colour Group likelihood curves** (owner ask, 2026-08-17: "Groups can also
have likelihood curves, default is flat one, but these don't overwrite they
multiply with the child likelihood curve"). No new storage shape: a Group
is a ColorSetCard like a Set, so a Group's curve lives in the SAME
`SequencerConfig.color_set_entries` dict, keyed by the GROUP's own card id
— nothing distinguishes a group's entry from a set's entry structurally,
same reuse the owner asked for. A Group is never itself a candidate in this
selector (color_wheel.wheel_positions/`_default_eligible_sets` still filter
to kind=="set" — a Group has no wheel position of its own, unchanged); its
curve instead multiplies onto every member SET's own score, resolved via
`Candidate.group_points` (one resolved curve per enclosing group, built by
the caller's own reverse "which groups contain this set" lookup — the
kernel stays pure and never queries colour-set storage itself).

A set under MORE THAN ONE group (real data: 4 of the Admiral's sets sit
under both "First Group" and "Blues") CHAINS every enclosing group's curve
by further multiplication, not "one wins" — the same multiplicative
philosophy as curve × genre × wheel, extended, not special-cased. A group
with NO entry in `color_set_entries` resolves through the same
`resolve_curve` default every other missing entry already gets: flat 1.0,
an exact float identity under multiplication (see group_curve_mult).

Compounding is real and undocumented magnitudes could starve a set
silently, so two things keep it honest rather than adding a hidden floor
or clamp (a clamp would quietly distort an authored curve's real shape):
(1) the ladder gets its own "drop group curves" rung — a set only zeroed
out by an enclosing group's curve at this intensity is NOT permanently
vetoed, it recovers the moment every other candidate is equally exhausted,
the same recoverability wheel-travel and genre already have; only the
SET'S OWN curve hitting zero is a true, ladder-proof veto, unchanged from
before groups existed. (2) `Pick.factors` carries the resolved `group`
multiplier per candidate at the FULL rung (alongside curve/genre/wheel/
score) so a silently-starved set is visible in the same status-strip/
sequencer_pick observability surface that already explains every other
pick — never a mystery a human has to guess at.

select_from_scene_pool is a separate, simpler mechanism, not a fourth
selector flavour of the above: a trigger's own inline scene_pool
(models.trigger.FireSceneAction.scene_pool) is a pure weighted draw over
its own weights only, no curve/genre/affinity/ladder — see its own
docstring and models/trigger.py's SCENE POOLS section.

Executable spec: scripts/check_sequencer.py, scripts/check_trigger_scene_pools.py
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from random import Random

from spectra.models.sequencer import (AffinityEdge, CurvePoint, CurveProfile,
                                      SelectorEntry)
from spectra.models.trigger import ScenePoolMember

WHEEL_HALF_TURN_DEG = 180.0

# Terminal rung per selector kind (decision 2).
TERMINAL_STAY = "stay"          # scenes: a room must always show something
TERMINAL_NOTHING = "nothing"    # flares: the all-gated-out answer is silence
TERMINAL_KEEP = "keep_colors"   # colour sets: never forced to churn

# Ladder rung names, in order. "full" is the normal (non-fallback) draw.
RUNG_FULL = "full"
RUNG_NO_AFFINITY = "no_affinity"
RUNG_NO_GENRE = "no_genre"
RUNG_READMIT_CURRENT = "readmit_current"
RUNG_UNIFORM = "uniform"
RUNG_NO_WHEEL = "no_wheel_travel"   # colour ladder only
RUNG_NO_GROUP = "no_group_curve"    # colour ladder only, dropped before wheel


def curve_eval(points: list[CurvePoint], x: float) -> float:
    """Piecewise-linear curve height at x.

    - Clamped flat outside the outer points (a 1-point curve is a constant —
      one flat point ≡ scalar weight).
    - Points share sorted x; equal x is a step discontinuity, and at exactly
      that x the LATER point wins. This makes the legacy energy_floor gate an
      exact 3-point curve: [(0,0), (f,0), (f,w)] is 0 below f, w from f up.
    """
    if not points:
        raise ValueError("curve_eval needs at least one point")
    if x < points[0].x:
        return points[0].y
    for i in range(len(points) - 1, -1, -1):
        if points[i].x <= x:
            if points[i].x == x or i == len(points) - 1:
                return points[i].y
            nxt = points[i + 1]
            t = (x - points[i].x) / (nxt.x - points[i].x)
            return points[i].y + t * (nxt.y - points[i].y)
    return points[0].y


def resolve_curve(entry: SelectorEntry,
                  profiles: dict[str, CurveProfile]) -> list[CurvePoint]:
    """An entry's effective curve: named profile → inline escape hatch →
    flat 1.0 (no curve ≡ scalar weight 1). A dangling curve_ref also falls
    back to flat 1.0 — the API rejects dangling refs at write time, so this
    only covers a hand-edited storage file."""
    if entry.curve_ref is not None and entry.curve_ref in profiles:
        return profiles[entry.curve_ref].points
    if entry.inline_points is not None:
        return entry.inline_points
    return [CurvePoint(x=0.0, y=1.0)]


def compose(curve_y: float, genre_mult: float, affinity_mult: float) -> float:
    """Decision 1: three separately-authored factors MULTIPLY into one score.
    Multiplicative keeps zero an honest veto from any factor."""
    return curve_y * genre_mult * affinity_mult


def group_curve_mult(group_points: list[list[CurvePoint]], x: float) -> float:
    """The colour-set selector's fourth multiplicand: the product of every
    enclosing group's own curve height at x. Empty list (a set in no group,
    or every enclosing group's entry resolved to flat) is the identity 1.0 —
    multiplying by it must leave the set's own score EXACTLY unchanged, not
    approximately, so ungrouped/default-group sets never quietly drift.
    A set under N groups CHAINS all N heights by further multiplication —
    see module docstring for why chaining, not "one wins", is the rule."""
    result = 1.0
    for points in group_points:
        result *= curve_eval(points, x)
    return result


@dataclass(frozen=True)
class Candidate:
    """One drawable thing, factors already resolved for this moment.
    affinity_mult is the scene selector's third factor; wheel_mult and
    group_points the colour-set selector's — each flavour reads its own and
    leaves the others at their neutral defaults. group_points is a list of
    already-resolved curves (one per enclosing Colour Group), evaluated and
    chained by group_curve_mult at draw time — resolving WHICH groups a set
    belongs to is the caller's job (kernel stays pure, no colour-set I/O)."""
    id: str
    points: list[CurvePoint]
    genre_mult: float = 1.0
    affinity_mult: float = 1.0
    wheel_mult: float = 1.0
    group_points: list[list[CurvePoint]] = field(default_factory=list)


@dataclass(frozen=True)
class Pick:
    """A selection outcome. picked_id None == the terminal rung fired
    (rung == TERMINAL_STAY or TERMINAL_NOTHING)."""
    picked_id: str | None
    rung: str
    intensity: float
    # Scores at the winning rung (what the draw actually used).
    scores: dict[str, float] = field(default_factory=dict)
    # Full factor breakdown per candidate at the FULL rung — observability
    # for the status strip / sequencer_pick broadcast.
    factors: dict[str, dict[str, float]] = field(default_factory=dict)


def _draw(scores: dict[str, float], rng: Random) -> str | None:
    """Weighted proportional draw. None when no candidate has a positive,
    finite score — the rung fails and the ladder descends."""
    ids = [cid for cid, s in scores.items() if s > 0.0 and math.isfinite(s)]
    if not ids:
        return None
    weights = [scores[cid] for cid in ids]
    return rng.choices(ids, weights=weights, k=1)[0]


def select_from_scene_pool(pool: list[ScenePoolMember], rng: Random,
                           existing_ids: set[str] | None = None) -> str | None:
    """A trigger's own scene_pool (models.trigger.FireSceneAction.scene_pool):
    a pure weighted-random draw over the pool's own weights only, reusing
    _draw's zero-veto/positive-finite-score discipline — deliberately NOT
    curve/genre/affinity-composed, unlike select() above. Mirrors legacy's
    scene_group_mode="weighted" and the already-shipped color_set_groups.py
    weighted branch: a self-contained pool, not a scored candidate ladder.
    existing_ids (when given) drops members whose scene no longer exists
    before drawing. None means nothing in the pool is both present and
    positively weighted — nothing fires this crossing."""
    scores = {m.scene_id: m.weight for m in pool
             if existing_ids is None or m.scene_id in existing_ids}
    return _draw(scores, rng)


def select(candidates: list[Candidate], *, intensity: float, rng: Random,
           current_id: str | None = None,
           terminal: str = TERMINAL_STAY) -> Pick:
    """Decision 2 shipped: weighted draw over composed scores with the
    deterministic fallback ladder. current_id (the active scene) is excluded
    until the re-admit rung; pass None for selectors with no "current" (flares).
    """
    curve_y = {c.id: curve_eval(c.points, intensity) for c in candidates}
    factors = {
        c.id: {
            "curve": curve_y[c.id],
            "genre": c.genre_mult,
            "affinity": c.affinity_mult,
            "score": compose(curve_y[c.id], c.genre_mult, c.affinity_mult),
        }
        for c in candidates
    }
    others = [c for c in candidates if c.id != current_id]

    rungs: list[tuple[str, dict[str, float]]] = [
        (RUNG_FULL,
         {c.id: compose(curve_y[c.id], c.genre_mult, c.affinity_mult) for c in others}),
        (RUNG_NO_AFFINITY,
         {c.id: compose(curve_y[c.id], c.genre_mult, 1.0) for c in others}),
        (RUNG_NO_GENRE,
         {c.id: curve_y[c.id] for c in others}),
        (RUNG_READMIT_CURRENT,
         {c.id: curve_y[c.id] for c in candidates}),
        (RUNG_UNIFORM,
         {c.id: 1.0 for c in candidates if curve_y[c.id] > 0.0}),
    ]
    for rung, scores in rungs:
        picked = _draw(scores, rng)
        if picked is not None:
            return Pick(picked_id=picked, rung=rung, intensity=intensity,
                        scores=scores, factors=factors)
    return Pick(picked_id=None, rung=terminal, intensity=intensity,
                factors=factors)


def select_flare(candidates: list[Candidate], *, intensity: float,
                 rng: Random) -> Pick:
    """Flare selector (decision 3): curve × genre only. Callers build
    candidates with affinity_mult=1.0 (there is no third factor to resolve);
    no current to exclude or re-admit; terminal rung fires NOTHING."""
    return select(candidates, intensity=intensity, rng=rng,
                  current_id=None, terminal=TERMINAL_NOTHING)


def select_color_set(candidates: list[Candidate], *, intensity: float,
                     rng: Random, current_id: str | None = None) -> Pick:
    """Colour-set selector (decision 3, +group curves): curve × genre ×
    wheel-travel × group over a weighted draw, with the colour ladder —
    drop group curves → drop wheel-travel → drop genre → uniform among
    curve-eligible → terminal KEEP the current colours.

    The current set is excluded from every rung (all live colour groups run
    exclude_current today); there is no re-admit rung because the terminal
    already keeps the room's palette — picked_id None with rung
    TERMINAL_KEEP means "change nothing", never "go dark"."""
    curve_y = {c.id: curve_eval(c.points, intensity) for c in candidates}
    group_y = {c.id: group_curve_mult(c.group_points, intensity) for c in candidates}
    factors = {
        c.id: {
            "curve": curve_y[c.id],
            "genre": c.genre_mult,
            "wheel": c.wheel_mult,
            "group": group_y[c.id],
            "score": compose(curve_y[c.id], c.genre_mult, c.wheel_mult) * group_y[c.id],
        }
        for c in candidates
    }
    others = [c for c in candidates if c.id != current_id]

    rungs: list[tuple[str, dict[str, float]]] = [
        (RUNG_FULL,
         {c.id: compose(curve_y[c.id], c.genre_mult, c.wheel_mult) * group_y[c.id]
          for c in others}),
        (RUNG_NO_GROUP,
         {c.id: compose(curve_y[c.id], c.genre_mult, c.wheel_mult) for c in others}),
        (RUNG_NO_WHEEL,
         {c.id: compose(curve_y[c.id], c.genre_mult, 1.0) for c in others}),
        (RUNG_NO_GENRE,
         {c.id: curve_y[c.id] for c in others}),
        (RUNG_UNIFORM,
         {c.id: 1.0 for c in others if curve_y[c.id] > 0.0}),
    ]
    for rung, scores in rungs:
        picked = _draw(scores, rng)
        if picked is not None:
            return Pick(picked_id=picked, rung=rung, intensity=intensity,
                        scores=scores, factors=factors)
    return Pick(picked_id=None, rung=TERMINAL_KEEP, intensity=intensity,
                factors=factors)


def genre_multiplier(entry: SelectorEntry, bucket: str | None) -> float:
    """Entry's multiplier for the song's genre bucket (training-profile name,
    matched case-insensitively). No bucket / no stated multiplier = neutral
    ×1.0 — sparse authoring never vetoes by omission."""
    if bucket is None:
        return 1.0
    if bucket in entry.genre_mult:
        return entry.genre_mult[bucket]
    lowered = bucket.lower()
    for name, mult in entry.genre_mult.items():
        if name.lower() == lowered:
            return mult
    return 1.0


def affinity_multiplier(affinity: list[AffinityEdge], from_id: str | None,
                        to_id: str) -> float:
    """Directional mult(prev → candidate); sparse table, default 1.0.
    Self-pairs are never stored (the diagonal IS dwell_weight) so from==to
    can't match an edge."""
    if from_id is None:
        return 1.0
    for edge in affinity:
        if edge.from_id == from_id and edge.to_id == to_id:
            return edge.mult
    return 1.0


def build_scene_candidates(entries: dict[str, SelectorEntry],
                           curves: dict[str, CurveProfile],
                           affinity: list[AffinityEdge], *,
                           genre_bucket: str | None,
                           prev_id: str | None,
                           restrict_ids: set[str] | None = None) -> list[Candidate]:
    """Scene-selector candidates with all three factors resolved.
    restrict_ids (when given) drops entries whose scene no longer exists."""
    return [
        Candidate(
            id=eid,
            points=resolve_curve(entry, curves),
            genre_mult=genre_multiplier(entry, genre_bucket),
            affinity_mult=affinity_multiplier(affinity, prev_id, eid),
        )
        for eid, entry in entries.items()
        if restrict_ids is None or eid in restrict_ids
    ]


def build_flare_candidates(entries: dict[str, SelectorEntry],
                           curves: dict[str, CurveProfile], *,
                           genre_bucket: str | None) -> list[Candidate]:
    """Flare-selector candidates: curve × genre, no third factor (decision 3)."""
    return [
        Candidate(
            id=eid,
            points=resolve_curve(entry, curves),
            genre_mult=genre_multiplier(entry, genre_bucket),
        )
        for eid, entry in entries.items()
    ]


def build_color_set_candidates(entries: dict[str, SelectorEntry],
                               curves: dict[str, CurveProfile], *,
                               genre_bucket: str | None,
                               room_deg: float | None,
                               set_positions: dict[str, float | None],
                               wheel_points: list[CurvePoint],
                               group_ids_by_set: dict[str, list[str]] | None = None
                               ) -> list[Candidate]:
    """Colour-set-selector candidates with all four factors resolved.

    set_positions is the eligibility gate AND the geometry: only entries
    keyed there become candidates (the caller has already applied the
    two-way scene/set filter and dropped deleted sets), and each value is
    the set's wheel position — None for rainbow/achromatic sets, which
    makes wheel_travel_mult neutral ×1.0 (the binding rainbow exemption).
    room_deg None (no chromatic set has fired yet) is neutral for everyone.

    group_ids_by_set (when given) maps a set id to every Colour Group that
    lists it as a member — the caller's own reverse lookup over colour-set
    storage (the kernel never reads that storage itself). Each named group
    id is resolved against the SAME `entries` dict a set's own curve comes
    from (a group's curve lives there too, keyed by the group's own card
    id) via resolve_curve, so a group with no entry is the same flat-1.0
    default every other missing entry already gets. Missing/None resolves
    to no groups — every existing caller that doesn't pass it is unaffected.
    """
    group_ids_by_set = group_ids_by_set or {}
    flat_entry = SelectorEntry()
    return [
        Candidate(
            id=eid,
            points=resolve_curve(entry, curves),
            genre_mult=genre_multiplier(entry, genre_bucket),
            wheel_mult=wheel_travel_mult(wheel_points, room_deg,
                                         set_positions[eid]),
            group_points=[resolve_curve(entries.get(gid, flat_entry), curves)
                          for gid in group_ids_by_set.get(eid, [])],
        )
        for eid, entry in entries.items()
        if eid in set_positions
    ]


def resolve_dwell_songs(dwell_weight: float, rng: Random) -> int:
    """Dwell target in SONGS for transition mode (decision 5): base is one
    song, so weight 2 holds ~2 songs. Fractional weights resolve
    probabilistically at adoption time — 1.5 holds one song half the time,
    two the other half — so the MEAN hold stays exactly proportional to the
    weight (report Part 3)."""
    whole = math.floor(dwell_weight)
    frac = dwell_weight - whole
    return whole + (1 if rng.random() < frac else 0)


def wheel_travel_deg(from_deg: float | None, to_deg: float | None) -> float | None:
    """Shortest arc between two wheel positions, 0–180°.

    None when either side has no position — a rainbow set (chromatic span >
    180°, services/color_wheel.py) or an achromatic set. That None IS the
    binding rainbow exemption: such sets are everywhere and nowhere on the
    wheel and sit outside every rotation-flavored mechanic.
    """
    if from_deg is None or to_deg is None:
        return None
    d = abs(from_deg - to_deg) % 360.0
    return min(d, 360.0 - d)


def wheel_travel_mult(points: list[CurvePoint], from_deg: float | None,
                      to_deg: float | None) -> float:
    """Wheel-travel likelihood factor; rainbow/achromatic sets are neutral ×1.0.

    The travel axis maps 0–180° onto the curve's 0–1 x-axis. This is the
    colour-set selector's third factor (decision 3); the exemption is
    binding wherever sets appear.
    """
    travel = wheel_travel_deg(from_deg, to_deg)
    if travel is None:
        return 1.0
    return curve_eval(points, travel / WHEEL_HALF_TURN_DEG)
