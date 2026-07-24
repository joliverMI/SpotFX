"""
Seed / re-seed the "Orbits" color group as a copy of "Black Holes".

Copies the "Black Holes" group and its 7 member Sets into "Orbits" /
"Orbit - <Color>" cards. Everything is identical except the Matrix entry:
instead of a solid in the chosen color, it becomes a linear gradient centered
on the chosen color's hue and spanning 90 degrees of the color wheel
(hue-45 .. hue+45, keeping the chosen color's saturation/value).

Deterministic UUIDs (uuid5) so re-running upserts the same cards.

USAGE
  .venv/bin/python scripts/seed_orbits_colorsets.py   # POST to running SpotFX
"""
from __future__ import annotations

import colorsys
import copy
import json
import re
import sys
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"

NS = uuid.NAMESPACE_DNS
GROUP_BLACK_HOLES = "90249415-7bdb-4d15-a3d3-214a15c5c225"
GROUP_ORBITS = str(uuid.uuid5(NS, "spotfx-orbits-colorgroup"))

HUE_SPAN_DEG = 90.0
STOP_COUNT = 5  # gradient stops across the span


def api(path: str, payload=None):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def hue_span_gradient(center_hex: str) -> str:
    """linear-gradient sweeping HUE_SPAN_DEG of the wheel, centered on center_hex."""
    r, g, b = hex_to_rgb(center_hex)
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    stops = []
    for i in range(STOP_COUNT):
        frac = i / (STOP_COUNT - 1)
        hue = (h + (frac - 0.5) * (HUE_SPAN_DEG / 360.0)) % 1.0
        sr, sg, sb = (round(c * 255) for c in colorsys.hsv_to_rgb(hue, s, v))
        stops.append(f"rgb({sr},{sg},{sb}) {round(frac * 100)}%")
    return f"linear-gradient(90deg, {', '.join(stops)})"


def is_matrix_entry(entry: dict) -> bool:
    return entry.get("scope", {}).get("categories") == ["Matrix"]


def main() -> None:
    cards = {c["id"]: c for c in api("/api/color-sets")}
    src_group = cards.get(GROUP_BLACK_HOLES)
    if not src_group:
        sys.exit("Black Holes group not found — aborting.")

    new_members = []
    for member in src_group["members"]:
        src = cards[member["color_set_id"]]
        new_set = copy.deepcopy(src)
        new_set["name"] = re.sub(r"^Black Hole", "Orbit", src["name"])
        new_set["id"] = str(uuid.uuid5(NS, f"spotfx-orbits-colorset-{new_set['name']}"))

        matrix = [e for e in new_set["entries"] if is_matrix_entry(e)]
        if len(matrix) != 1:
            sys.exit(f"{src['name']}: expected exactly 1 Matrix entry, got {len(matrix)}")
        center = matrix[0]["color_value"]
        matrix[0]["color_kind"] = "gradient"
        matrix[0]["color_value"] = hue_span_gradient(center)

        api("/api/color-sets", new_set)
        new_members.append({"color_set_id": new_set["id"], "weight": member["weight"]})
        print(f"upserted set   {new_set['name']} ({new_set['id']})  center={center}")

    group = copy.deepcopy(src_group)
    group["id"] = GROUP_ORBITS
    group["name"] = "Orbits"
    group["members"] = new_members
    api("/api/color-sets", group)
    print(f"upserted group Orbits ({GROUP_ORBITS})")


if __name__ == "__main__":
    main()
