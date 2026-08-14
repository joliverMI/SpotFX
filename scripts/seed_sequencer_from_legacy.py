#!/usr/bin/env python3
"""Seed sequencer curve profiles/entries from the legacy chooser machinery.
DRY-RUN by default (prints the diff table); --apply writes
storage/spectra/sequencer.json through spectra.services.sequencer_store
(atomic, idempotent) — SPECTRA reads her own store after the process split,
not the legacy storage/sequencer.json (spot-effects side, unread by her).

Translates:
  - Intensity-chooser lane thresholds (the load-bearing 'Intensity Scene'
    bands [0, 0.3, 0.65, 0.85, 0.95]) → named band CurveProfiles (trapezoids
    with 0.1 skirts) — the five band profiles of decision 4. Profile identity
    is the NAME: re-running --apply updates points in place, never duplicates.
  - Each lane's referenced scenes → SelectorEntries on their SPECTRA SceneV2
    counterparts (spectra.services.scene_store — her own scene store, which
    may hold scenes authored directly through her API and absent from the
    legacy storage/scenes_v2.json; matched by name: exact case-insensitive,
    then the "<name> V2" rebuild convention, then SCENE_RENAMES for the rest
    — see resolve_v2_id). Weight 1.0 members
    reference the shared band profile (curve_ref); other weights get INLINE
    points — the same shape at weight× height is a one-off, which is exactly
    what the escape hatch is for. Legacy scenes with no SceneV2 counterpart
    are SKIPPED (create the V2 scene, re-run). Outlier weights (>= 10, e.g.
    the live 100.0 force-favorite hack) are FLAGGED for manual affinity
    translation, not blindly seeded.
  - RandomOption energy gates (floor/ceiling/scale) → step + tilt curves,
    printed for reference ONLY (gate_curve rows): they belong to random
    options inside composites, not to scenes — nothing to attach them to.
    Sole exactness caveat: at exactly x==ceiling the curve reads 0 where the
    legacy gate still admits the option.
  - Dwell weights all 1.0 (no legacy signal exists — today's model is one
    global timer). Genre multipliers and affinity are NOT seeded — they are
    authored by telling the agent.
  - Colour sets (decision 3, wired last): every kind="set" member of a legacy
    colour group (storage/color_sets.json) → a colour SelectorEntry keyed by
    the SAME card id (no name mapping — both paths share the store). All live
    weights are 1.0 → the default flat-1.0 curve; the room's palette walk is
    carried by the wheel-travel factor instead: a default DOWNHILL profile
    ("prefer small steps", (0,1)→(1,0)) is seeded and installed as
    config.wheel_travel_curve, approximating today's deterministic
    palette-sync hue-anchored stepping. Rainbow sets are seeded like any
    other (they stay eligible via curves; the wheel exemption is the
    kernel's). Dark/Light variant member pools are NOT seeded — variants are
    a legacy display-mode mechanism.

--apply merges: seeded entries replace same-scene/same-set entries; unseeded
entries, affinity, flare_entries, change_mode and the enabled flag are
preserved; wheel_travel_curve is only set when currently unset.
The sequencer stays dark (enabled defaults False) after seeding.

Usage:
    .venv/bin/python scripts/seed_sequencer_from_legacy.py           # diff table
    .venv/bin/python scripts/seed_sequencer_from_legacy.py --apply   # write
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Iterator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.sequencer import CurvePoint, CurveProfile, SelectorEntry

BAND_SKIRT = 0.1
OUTLIER_WEIGHT = 10.0
WHEEL_PROFILE_NAME = "Wheel travel — prefer small steps"

# Legacy lane scene name → rebuilt SceneV2 name, for renames that don't fit
# the "<name> V2" convention below (decision: the owner's SceneV2 rebuild).
SCENE_RENAMES = {"Mid Star": "STAR"}


def resolve_v2_id(scene_name: str, v2_name_to_id: dict[str, str]) -> str | None:
    """Match a legacy lane scene name to its rebuilt SceneV2 id: exact
    (case-insensitive) first, then the "<name> V2" rebuild convention, then
    SCENE_RENAMES for the handful that don't fit that convention."""
    v2_id = v2_name_to_id.get(scene_name.lower())
    if v2_id is not None:
        return v2_id
    v2_id = v2_name_to_id.get(f"{scene_name} V2".lower())
    if v2_id is not None:
        return v2_id
    renamed = SCENE_RENAMES.get(scene_name)
    if renamed is not None:
        return v2_name_to_id.get(renamed.lower())
    return None


def wheel_profile_points() -> list[CurvePoint]:
    """The default downhill wheel-travel curve: most likely at no travel,
    fading linearly to 0 at the opposite side of the wheel (x 1 ≡ 180°)."""
    return [CurvePoint(x=0.0, y=1.0), CurvePoint(x=1.0, y=0.0)]


# ── pure translation helpers (spec-covered: scripts/check_sequencer.py) ──────

def band_edges(thresholds: list[float]) -> list[tuple[float, float]]:
    """Chooser lane thresholds (lower bounds, lanes[0]'s ignored ≡ 0.0) →
    [lo, hi) bands covering 0–1."""
    edges = sorted(set(thresholds) | {0.0})
    return [(lo, hi) for lo, hi in zip(edges, edges[1:] + [1.0]) if hi > lo]


def band_points(lo: float, hi: float, skirt: float = BAND_SKIRT) -> list[CurvePoint]:
    """Trapezoid: full height across [lo, hi], linear skirts fading to 0
    outside. A band touching an end of the axis has no skirt on that side
    (curve_eval clamps flat there anyway)."""
    points: list[CurvePoint] = []
    if lo > 0.0:
        points.append(CurvePoint(x=round(max(0.0, lo - skirt), 6), y=0.0))
    points.append(CurvePoint(x=lo, y=1.0))
    points.append(CurvePoint(x=hi, y=1.0))
    if hi < 1.0:
        points.append(CurvePoint(x=round(min(1.0, hi + skirt), 6), y=0.0))
    return points


def gate_points(floor: float | None, ceiling: float | None,
                scale: float = 0.0) -> list[CurvePoint]:
    """RandomOption energy gate → curve. Weight inside [floor, ceiling] is the
    legacy tilt 1+scale·(2t−1) (a straight line); zero outside via step
    discontinuities."""
    lo = floor if floor is not None else 0.0
    hi = ceiling if ceiling is not None else 1.0
    y_lo = max(0.0, 1.0 - scale)
    y_hi = max(0.0, 1.0 + scale)
    points: list[CurvePoint] = []
    if lo > 0.0:
        points += [CurvePoint(x=0.0, y=0.0), CurvePoint(x=lo, y=0.0)]
    points.append(CurvePoint(x=lo, y=y_lo))
    if hi > lo:
        points.append(CurvePoint(x=hi, y=y_hi))
    if hi < 1.0:
        points.append(CurvePoint(x=hi, y=0.0))
    return points


def scale_points(points: list[CurvePoint], weight: float) -> list[CurvePoint]:
    """Legacy member weight → same shape at weight× height."""
    return [CurvePoint(x=p.x, y=p.y * weight) for p in points]


# ── legacy storage walk (read-only) ──────────────────────────────────────────

def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _referenced_event_ids(lane: dict) -> list[str]:
    ids = []
    for d in _walk(lane):
        if d.get("type") == "event_ref" and d.get("event_id"):
            ids.append(d["event_id"])
        elif d.get("step_type") == "event" and d.get("event_id"):
            ids.append(d["event_id"])
    return ids


def _fmt_points(points: list[CurvePoint]) -> str:
    return " ".join(f"({p.x:g},{p.y:g})" for p in points)


@dataclass
class SeedPlan:
    """What an apply writes, plus the human diff table."""
    profiles: list[CurveProfile] = field(default_factory=list)   # identity = name
    entries: dict[str, SelectorEntry] = field(default_factory=dict)  # SceneV2 id → entry
    color_entries: dict[str, SelectorEntry] = field(default_factory=dict)  # ColorSetCard id → entry
    wheel_profile: CurveProfile | None = None   # also present in profiles
    rows: list[tuple[str, str, str]] = field(default_factory=list)   # (kind, name, detail)


def build_seed(events: list[dict], v2_name_to_id: dict[str, str],
               color_cards: list | None = None) -> SeedPlan:
    """Translate legacy events into the seed plan. v2_name_to_id maps
    lowercased SceneV2 names → ids (empty dict = every scene SKIPPED).
    color_cards (list[ColorSetCard]) enables the colour-set translation;
    None skips it entirely — no colour entries, no wheel profile."""
    by_id = {e.get("id"): e for e in events}
    plan = SeedPlan()

    def add_entry(scene_name: str, profile: CurveProfile, weight: float) -> None:
        v2_id = resolve_v2_id(scene_name, v2_name_to_id)
        if v2_id is None:
            plan.rows.append(("SKIPPED", scene_name,
                              "no SceneV2 counterpart by that name — create it "
                              "and re-run"))
            return
        if v2_id in plan.entries:
            plan.rows.append(("FLAGGED", scene_name,
                              "appears in more than one band — keeping the first, "
                              "merge curves by hand if both should count"))
            return
        if weight == 1.0:
            entry = SelectorEntry(curve_ref=profile.id)
            detail = f"profile '{profile.name}', dwell_weight 1.0"
        else:
            entry = SelectorEntry(inline_points=scale_points(profile.points, weight))
            detail = (f"profile '{profile.name}' at {weight:g}× height "
                      "(inline escape hatch), dwell_weight 1.0")
        plan.entries[v2_id] = entry
        plan.rows.append(("entry", scene_name, detail))

    for event in events:
        for node in _walk(event):
            if node.get("type") != "intensity_chooser":
                continue
            if node.get("source", "trigger_intensity") != "trigger_intensity":
                continue
            lanes = node.get("lanes") or []
            thresholds = [l.get("threshold", 0.0) for l in lanes[1:]]
            bands = band_edges(thresholds)
            band_of_lane: dict[int, tuple[float, float]] = {}
            for i, lane in enumerate(lanes):
                lane_lo = 0.0 if i == 0 else lane.get("threshold", 0.0)
                for lo, hi in bands:
                    if lo == lane_lo:
                        band_of_lane[i] = (lo, hi)
            for i, lane in enumerate(lanes):
                if i not in band_of_lane:
                    continue
                lo, hi = band_of_lane[i]
                profile = CurveProfile(
                    name=f"{event.get('name', '?')} band {lo:g}–{hi:g}",
                    points=band_points(lo, hi))
                plan.profiles.append(profile)
                plan.rows.append(("curve_profile", profile.name,
                                  _fmt_points(profile.points)))
                for eid in _referenced_event_ids(lane):
                    target = by_id.get(eid, {})
                    tname = target.get("name", eid)
                    if target.get("event_type") == "scene_group":
                        for member in target.get("scene_group_members") or []:
                            weight = member.get("weight", 1.0)
                            m = by_id.get(member.get("event_id"), {})
                            mname = str(m.get("name", member.get("event_id")))
                            if weight >= OUTLIER_WEIGHT:
                                plan.rows.append(("FLAGGED", f"{tname} → {mname}",
                                                  f"weight {weight:g} outlier — translate to "
                                                  "affinity/curve by hand, not seeded"))
                            else:
                                add_entry(mname, profile, weight)
                    else:
                        add_entry(str(tname), profile, 1.0)

    for event in events:
        for node in _walk(event):
            floor, ceiling = node.get("energy_floor"), node.get("energy_ceiling")
            scale = node.get("energy_scale") or 0.0
            if floor is None and ceiling is None and not scale:
                continue
            if "options" in node or "weight" not in node:
                continue   # only RandomOption-shaped dicts carry the gate
            name = node.get("name") or node.get("id", "?")
            plan.rows.append(("gate_curve", f"option '{name}' in '{event.get('name', '?')}'",
                              f"floor={floor} ceiling={ceiling} scale={scale:g} → "
                              f"{_fmt_points(gate_points(floor, ceiling, scale))} "
                              "(reference only — random-option gates attach to "
                              "nothing in the sequencer)"))

    if color_cards is not None:
        _seed_colors(plan, color_cards)
    return plan


def _seed_colors(plan: SeedPlan, color_cards: list) -> None:
    """Colour-set translation: the downhill wheel-travel profile plus one
    flat-curve entry per set referenced by any legacy colour group. Card ids
    are shared with the legacy path, so entries key directly on them."""
    from services import color_wheel

    plan.wheel_profile = CurveProfile(name=WHEEL_PROFILE_NAME,
                                      points=wheel_profile_points())
    plan.profiles.append(plan.wheel_profile)
    plan.rows.append(("curve_profile", WHEEL_PROFILE_NAME,
                      _fmt_points(plan.wheel_profile.points)
                      + " — installed as wheel_travel_curve when unset"))

    sets = {c.id: c for c in color_cards if c.kind == "set"}
    for group in color_cards:
        if group.kind != "group":
            continue
        for member in group.members:
            card = sets.get(member.color_set_id)
            if card is None:
                plan.rows.append(("SKIPPED", f"{group.name} → {member.color_set_id}",
                                  "member references no existing colour set"))
                continue
            if card.id in plan.color_entries:
                continue   # a set in several groups still gets ONE entry
            weight = member.weight
            if weight >= OUTLIER_WEIGHT:
                plan.rows.append(("FLAGGED", f"{group.name} → {card.name}",
                                  f"weight {weight:g} outlier — translate by "
                                  "hand, not seeded"))
                continue
            if weight == 1.0:
                entry = SelectorEntry()
                detail = "flat 1.0 curve"
            else:
                entry = SelectorEntry(
                    inline_points=[CurvePoint(x=0.0, y=weight)])
                detail = f"flat curve at {weight:g} (inline escape hatch)"
            position = color_wheel.wheel_position(card)
            wheel = ("rainbow — wheel-travel exempt" if position.rainbow
                     else "achromatic — wheel-travel exempt"
                     if position.position_deg is None
                     else f"wheel {position.position_deg:g}°")
            plan.color_entries[card.id] = entry
            plan.rows.append(("color_entry", card.name, f"{detail}; {wheel}"))


def apply_seed(plan: SeedPlan) -> tuple[int, int, int]:
    """Merge the plan into storage/spectra/sequencer.json (SPECTRA's own
    store — see module docstring). Profiles match existing ones BY NAME (id
    and unrelated profiles preserved); seeded entries replace same-scene/
    same-set entries; everything else in config — enabled, change_mode,
    affinity, flare_entries, unseeded entries, an already-set
    wheel_travel_curve — is preserved.
    Returns (profiles_written, entries_written, color_entries_written)."""
    from spectra.services import sequencer_store

    curves = sequencer_store.load_curves()
    id_by_name = {p.name: pid for pid, p in curves.items()}
    remap: dict[str, str] = {}   # plan profile id → stored profile id
    for profile in plan.profiles:
        existing_id = id_by_name.get(profile.name)
        if existing_id is not None:
            curves[existing_id] = CurveProfile(id=existing_id, name=profile.name,
                                               points=profile.points)
            remap[profile.id] = existing_id
        else:
            curves[profile.id] = profile
            remap[profile.id] = profile.id

    config = sequencer_store.load_config()
    for scene_id, entry in plan.entries.items():
        if entry.curve_ref is not None:
            entry = SelectorEntry(curve_ref=remap[entry.curve_ref],
                                  genre_mult=entry.genre_mult,
                                  dwell_weight=entry.dwell_weight)
        config.entries[scene_id] = entry
    for set_id, entry in plan.color_entries.items():
        config.color_set_entries[set_id] = entry
    if plan.wheel_profile is not None and config.wheel_travel_curve is None:
        config.wheel_travel_curve = remap[plan.wheel_profile.id]

    sequencer_store.save_curves(curves)
    sequencer_store.save_config(config)
    return len(plan.profiles), len(plan.entries), len(plan.color_entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="write storage/spectra/sequencer.json (default: dry-run diff table)")
    args = parser.parse_args()

    from services.profile_manager import EVENTS_FILE
    if EVENTS_FILE.exists():
        raw = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
        events = list(raw.values()) if isinstance(raw, dict) else list(raw)
    else:
        print(f"No legacy events file at {EVENTS_FILE} — no scene bands to "
              "translate; colour translation still runs.")
        events = []

    from services import color_set_store
    from spectra.services import scene_store as spectra_scene_store
    v2_name_to_id = {s.name.lower(): s.id for s in spectra_scene_store.list_all()}

    plan = build_seed(events, v2_name_to_id, color_set_store.list_all())
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{mode} — {len(plan.rows)} row(s), {len(plan.profiles)} profile(s), "
          f"{len(plan.entries)} scene entr(y/ies), "
          f"{len(plan.color_entries)} colour entr(y/ies).\n")
    if plan.rows:
        kind_w = max(len(r[0]) for r in plan.rows)
        name_w = max(len(r[1]) for r in plan.rows)
        for kind, name, detail in plan.rows:
            print(f"{kind:<{kind_w}}  {name:<{name_w}}  {detail}")

    if not args.apply:
        print("\nNothing written (dry run). Re-run with --apply to write "
              "storage/spectra/sequencer.json.")
        return 0

    n_profiles, n_entries, n_color = apply_seed(plan)
    from spectra.config import SEQUENCER_FILE
    print(f"\nWrote {SEQUENCER_FILE}: {n_profiles} profile(s), "
          f"{n_entries} scene entr(y/ies), {n_color} colour entr(y/ies) "
          "merged. Sequencer remains dark (config.enabled unchanged).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
