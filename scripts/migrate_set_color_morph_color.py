#!/usr/bin/env python3
"""
Migration: Morph Color rename + ambient-flip replacement.

1. Rename the Color Set action type: "morph_color" → "set_color"
   (the UI name changes from "Morph Color" to "Set Color"; shape unchanged).

2. Replace every legacy `ledfx_ambient_color` action ("ambient flip") with the
   NEW `morph_color` hue-rotation action — 180° forward, scoped to the
   "Singles" device category — matching each event's original timings:
     - "Flip Ambients":                bare action swap (default ramp).
     - "Ambient Flip and Back - Fast": swap; group revert (400ms/200ms) kept.
     - "Ambient Flip and Back - Slow": the 2.0s global-transition child is
       dropped and both rotations get ramp_ms=2000 (same visual speed).
     - "Contrast 2 Beat Fast":         swap both beat children (default ramp).
     - "Contrast 2 Beat Slow":         the 0.6s global-transition child is
       dropped and both rotations get ramp_ms=600.

Writes a timestamped backup to storage/backups/ before saving. Idempotent:
re-running after migration is a no-op.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS_FILE = ROOT / "storage" / "events.json"
BACKUP_DIR = ROOT / "storage" / "backups"

# event id → ramp_ms for the replacement rotation (None = engine default)
FLIP_RAMPS = {
    "7bb23fa7-271e-454e-b52d-51a9f2ab5f64": None,   # Flip Ambients
    "1c2226d5-94c8-4dd1-b4c8-ccfb0cfd37a3": None,   # Ambient Flip and Back - Fast
    "1651d7dc-f19c-45b6-bb39-4bd9480ececc": 2000,   # Ambient Flip and Back - Slow
    "9e9c8784-4489-4448-b2fd-a33da1863c49": None,   # Contrast 2 Beat Fast
    "fd8d10b2-188b-453b-9495-b97363c4aef8": 600,    # Contrast 2 Beat Slow
}
# event ids whose global_transition children existed only to pace the flip
DROP_TRANSITION_IDS = {
    "1651d7dc-f19c-45b6-bb39-4bd9480ececc",
    "fd8d10b2-188b-453b-9495-b97363c4aef8",
}

counts = {"renamed": 0, "flips": 0, "transitions_dropped": 0}


def rotate_action(old: dict, ramp_ms: int | None) -> dict:
    return {
        "type": "morph_color",
        "labels": list(old.get("labels") or []),
        "weight": old.get("weight", 1.0),
        "scope": {"virtual_ids": [], "categories": ["Singles"], "roles": []},
        "degrees": 180.0,
        "direction": "forward",
        "ramp_ms": ramp_ms,
        "intensity_scale": 0.0,
        "intensity_source": "rms_total",
        "preserve_melt_bg": False,
    }


def walk(node, ramp_ms, drop_transitions):
    """Recursively rename set_color and swap ambient flips in one event tree.
    Returns the (possibly replaced) node."""
    if isinstance(node, list):
        out = []
        for item in node:
            new = walk(item, ramp_ms, drop_transitions)
            if new is not None or item is None:
                out.append(new)
        node[:] = out
        return node
    if not isinstance(node, dict):
        return node

    t = node.get("type")
    if t == "morph_color" and "ref_id" in node:
        node["type"] = "set_color"
        counts["renamed"] += 1
    elif t == "ledfx_ambient_color":
        counts["flips"] += 1
        return rotate_action(node, ramp_ms)
    elif t == "ledfx_global_transition" and drop_transitions:
        counts["transitions_dropped"] += 1
        return None

    for key, val in list(node.items()):
        if val is None:
            continue  # keep literal JSON nulls untouched
        new = walk(val, ramp_ms, drop_transitions)
        if new is None:
            del node[key]  # a dropped global_transition stored directly under a key
        else:
            node[key] = new
    return node


def prune_empty_children(event: dict) -> None:
    """Drop sequence-group children left with no actions (a dropped
    global_transition was their only action)."""
    def _prune(node):
        if isinstance(node, list):
            for item in node:
                _prune(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") in ("sequence_group", "parallel_group"):
            node["children"] = [
                c for c in node.get("children") or [] if c.get("actions")
            ]
        for val in node.values():
            _prune(val)
    _prune(event)


def main() -> int:
    data = json.loads(EVENTS_FILE.read_text())

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"events-pre-setcolor-morphcolor-{stamp}.json"
    shutil.copy2(EVENTS_FILE, backup)

    for eid, event in data.items():
        walk(
            event,
            ramp_ms=FLIP_RAMPS.get(eid),
            drop_transitions=eid in DROP_TRANSITION_IDS,
        )
        if eid in DROP_TRANSITION_IDS:
            prune_empty_children(event)

    if not any(counts.values()):
        backup.unlink()
        print("Nothing to migrate — events.json already current.")
        return 0

    EVENTS_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"Backup: {backup}")
    print(f"Renamed morph_color → set_color: {counts['renamed']}")
    print(f"Ambient flips → new morph_color (Singles, 180°): {counts['flips']}")
    print(f"Pacing global_transition steps dropped: {counts['transitions_dropped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
