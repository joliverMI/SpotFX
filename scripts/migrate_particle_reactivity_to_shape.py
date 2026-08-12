#!/usr/bin/env python3
"""
One-off migration: particle_count moved from the Reactivity aspect to Shape,
where it overlaps radial's `edges` as the "Edge / Particle Count" sub-field.

Rewrites storage/events.json in place (with a timestamped backup in
storage/backups/): every morph_step target with aspect=reactivity that
addresses `particle_count` via reactivity_values / reactivity_nudges loses
that entry, and an equivalent Shape target (absolute `edges` value or
`edges_nudge` spec) is inserted right after it. Reactivity targets left with
nothing to do are dropped.

Usage: python3 scripts/migrate_particle_reactivity_to_shape.py [--dry-run]
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS_FILE = ROOT / "storage" / "events.json"
BACKUP_DIR = ROOT / "storage" / "backups"

stats = {"values": 0, "nudges": 0, "dropped_targets": 0, "events": set()}


def _is_noop_reactivity(target: dict) -> bool:
    av = target.get("absolute_value") or {}
    if av.get("reactivity_values") or av.get("reactivity_nudges"):
        return False
    if target.get("mode") == "nudge":
        return not (target.get("nudge_amount") or 0.0)
    return av.get("number") is None


def _shape_target_from(src: dict, mode: str) -> dict:
    return {
        "scope": copy.deepcopy(src.get("scope") or
                               {"virtual_ids": [], "categories": [], "roles": []}),
        "aspect": "shape",
        "mode": mode,
        "absolute_value": {},
        "nudge_amount": 0.0,
        "intensity_scale": 0.0,
        "ramp_ms": copy.deepcopy(src.get("ramp_ms")),
    }


def _migrate_targets(targets: list, event_id: str) -> None:
    i = 0
    while i < len(targets):
        t = targets[i]
        if not (isinstance(t, dict) and t.get("aspect") == "reactivity"):
            i += 1
            continue
        av = t.get("absolute_value") or {}
        val = (av.get("reactivity_values") or {}).pop("particle_count", None)
        spec = (av.get("reactivity_nudges") or {}).pop("particle_count", None)
        inserted = 0
        if val is not None:
            new_t = _shape_target_from(t, "absolute")
            # bindings (dicts) pass through untouched; numbers become ints
            new_t["absolute_value"]["edges"] = (
                val if isinstance(val, dict) else int(round(float(val))))
            targets.insert(i + 1, new_t)
            inserted += 1
            stats["values"] += 1
        if spec is not None:
            new_t = _shape_target_from(t, "nudge")
            new_t["absolute_value"]["edges_nudge"] = copy.deepcopy(spec)
            targets.insert(i + 1 + inserted, new_t)
            inserted += 1
            stats["nudges"] += 1
        if inserted:
            stats["events"].add(event_id)
            if _is_noop_reactivity(t):
                targets.pop(i)
                stats["dropped_targets"] += 1
                i += inserted
                continue
        i += 1 + inserted


def _walk(node, event_id: str) -> None:
    if isinstance(node, dict):
        if node.get("type") == "morph_step" and isinstance(node.get("targets"), list):
            _migrate_targets(node["targets"], event_id)
        for v in node.values():
            _walk(v, event_id)
    elif isinstance(node, list):
        for v in node:
            _walk(v, event_id)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    opts = ap.parse_args()

    data = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    for eid, ev in data.items():
        _walk(ev, f"{eid} ({ev.get('name', '?')})")

    total = stats["values"] + stats["nudges"]
    print(f"migrated {total} particle_count entries "
          f"({stats['values']} absolute, {stats['nudges']} nudge), "
          f"dropped {stats['dropped_targets']} emptied reactivity targets, "
          f"across {len(stats['events'])} events:")
    for e in sorted(stats["events"]):
        print(f"  - {e}")

    if opts.dry_run:
        print("dry run — nothing written")
        return 0
    if total:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        bak = BACKUP_DIR / f"events.json.bak-particle-migration-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(EVENTS_FILE, bak)
        print(f"backup: {bak}")
        tmp = EVENTS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(EVENTS_FILE)
        print(f"wrote {EVENTS_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
