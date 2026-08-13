#!/usr/bin/env python3
"""Seed sequencer curve profiles/entries from the legacy chooser machinery —
DRY-RUN ONLY.

Translates, without writing anything:
  - Intensity-chooser lane thresholds (the load-bearing 'Intensity Scene'
    bands [0, 0.3, 0.65, 0.85, 0.95]) → named band CurveProfiles (trapezoids
    with 0.1 skirts), assigned to each lane's referenced scene events.
  - Scene-group member weights → curve height scaling (weight 2.0 = same
    profile at 2× height). Outlier weights (>= 10, e.g. the live 100.0
    force-favorite hack) are flagged for manual affinity translation, not
    blindly seeded.
  - RandomOption energy gates (floor/ceiling/scale) → step + tilt curves,
    exact by construction: a floor f is the 3-point step [(0,0),(f,0),(f,y)]
    (at exactly x==f the later point wins — services/selection_kernel), the
    energy_scale tilt 1+scale·(2t−1) is literally a two-point line. Sole
    caveat: at exactly x==ceiling the curve reads 0 where the legacy gate
    still admits the option.
  - Dwell weights all 1.0 (no legacy signal exists — today's model is one
    global timer).

--apply REFUSES to run: the storage schema is not decision-final (captain
holds curve-ownership / colorset-flare-mechanism are open — report Part 4).
The flag exists so the eventual apply path has a stable CLI, nothing more.

Usage:
    .venv/bin/python scripts/seed_sequencer_from_legacy.py           # diff table
    .venv/bin/python scripts/seed_sequencer_from_legacy.py --apply   # refuses
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Iterator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.sequencer import CurvePoint, CurveProfile

BAND_SKIRT = 0.1
OUTLIER_WEIGHT = 10.0


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


def build_diff(events: list[dict]) -> list[tuple[str, str, str]]:
    """Rows of (kind, name, detail) describing what an apply WOULD write."""
    by_id = {e.get("id"): e for e in events}
    rows: list[tuple[str, str, str]] = []

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
                rows.append(("curve_profile", profile.name, _fmt_points(profile.points)))
                for eid in _referenced_event_ids(lane):
                    target = by_id.get(eid, {})
                    tname = target.get("name", eid)
                    if target.get("event_type") == "scene_group":
                        for member in target.get("scene_group_members") or []:
                            weight = member.get("weight", 1.0)
                            m = by_id.get(member.get("event_id"), {})
                            mname = m.get("name", member.get("event_id"))
                            if weight >= OUTLIER_WEIGHT:
                                rows.append(("FLAGGED", f"{tname} → {mname}",
                                             f"weight {weight:g} outlier — translate to "
                                             "affinity/curve by hand, not seeded"))
                            else:
                                rows.append(("entry", str(mname),
                                             f"profile '{profile.name}' at {weight:g}× "
                                             "height, dwell_weight 1.0"))
                    else:
                        rows.append(("entry", str(tname),
                                     f"profile '{profile.name}', dwell_weight 1.0"))

    for event in events:
        for node in _walk(event):
            floor, ceiling = node.get("energy_floor"), node.get("energy_ceiling")
            scale = node.get("energy_scale") or 0.0
            if floor is None and ceiling is None and not scale:
                continue
            if "options" in node or "weight" not in node:
                continue   # only RandomOption-shaped dicts carry the gate
            name = node.get("name") or node.get("id", "?")
            rows.append(("gate_curve", f"option '{name}' in '{event.get('name', '?')}'",
                         f"floor={floor} ceiling={ceiling} scale={scale:g} → "
                         f"{_fmt_points(gate_points(floor, ceiling, scale))}"))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="disabled — refuses until the storage schema is decision-final")
    args = parser.parse_args()

    if args.apply:
        print("REFUSED: --apply is disabled. The sequencer storage schema is not "
              "decision-final\n(open captain holds: curve-ownership, "
              "colorset-flare-mechanism — see\ndata/spectra-sequencing-design/report.md). "
              "Run without --apply for the diff table.")
        return 2

    from services.profile_manager import EVENTS_FILE
    if not EVENTS_FILE.exists():
        print(f"No legacy events file at {EVENTS_FILE} — nothing to translate.")
        return 0
    raw = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    events = list(raw.values()) if isinstance(raw, dict) else list(raw)

    rows = build_diff(events)
    print(f"DRY RUN — {len(rows)} row(s); nothing written.\n")
    if rows:
        kind_w = max(len(r[0]) for r in rows)
        name_w = max(len(r[1]) for r in rows)
        for kind, name, detail in rows:
            print(f"{kind:<{kind_w}}  {name:<{name_w}}  {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
