"""
Migrate storage/events.json to the unified composite event model.

Converts single / sequence / beat_sequence / morph_set / device_settings
events into event_type="composite" with an equivalent `root` Action tree.
Scene-family events (scene_update + fixed flares) stay legacy until v2.
Event ids never change, so profile triggers and event_refs are untouched.

USAGE
  .venv/bin/python scripts/migrate_to_composite.py            # DRY RUN (default)
  .venv/bin/python scripts/migrate_to_composite.py --apply    # backup + write

Dry-run prints the per-event mapping table and validates every produced
dict through MusicEvent(**d). --apply first copies events.json to
events.json.bak-<timestamp>; that backup doubles as the legacy twin for
scripts/check_composite_equivalence.py.

Idempotent: composite and scene-family events are skipped, so re-running
is a no-op.

MAPPING (dedupe-key continuity is deliberate):
  single ≥2 actions → root = random_group with id=event.id (preserves the
                      _last_action de-weighting key) and one option per
                      action carrying the action's labels/weight.
  single 1 action   → root = the action itself; 0 actions → root = None.
  sequence          → sequence_group(timing="ms"); step bodies fold the
                      legacy single `action` field into `actions`;
                      step_type="event" becomes an event_ref action.
  beat_sequence     → sequence_group(timing="beats") with per-child
                      delay_beats/pre_ramp + beat_fallback/start_offset.
  morph_set         → parallel_group; lanes with >1 alternatives wrap in a
                      random_group with id=f"{event.id}:lane:{li}" (the
                      legacy lane dedupe key); pre-commands disabled on the
                      event (morph_set never fired them — rule moves to data).
  device_settings   → root = a device_settings action.
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.music_event import MusicEvent  # noqa: E402

EVENTS_FILE = Path(__file__).resolve().parent.parent / "storage" / "events.json"
SCENE_TYPES = {
    "scene_update", "update_scene", "reset_scene",
    "shape_flare", "color_flare", "combo_flare",
}
LEGACY_BODY_RESET = {
    "actions": [], "sequence_steps": [], "beat_sequence_steps": [],
    "morph_lanes": [], "device_targets": [],
    "revert": None, "beat_revert": None,
    "beat_sequence_fallback": "fallback", "beat_sequence_start_offset_beats": 0,
}


def _uid() -> str:
    return str(uuid.uuid4())


def _event_ref(event_id: str | None) -> dict:
    return {"type": "event_ref", "event_id": event_id or "", "labels": [], "weight": 1.0}


def _step_body(step: dict) -> list[dict]:
    """Fold the legacy single `action` field; event steps become event_refs."""
    if step.get("step_type") == "event":
        return [_event_ref(step.get("event_id"))]
    actions = step.get("actions") or []
    if not actions and step.get("action"):
        actions = [step["action"]]
    return actions


def _wrap_random(alternatives: list[dict], group_id: str) -> list[dict]:
    """>1 alternatives → random_group preserving the legacy dedupe key; 1 → direct."""
    if len(alternatives) > 1:
        return [{
            "type": "random_group", "id": group_id, "labels": [], "weight": 1.0,
            "dedupe": True,
            "options": [
                {"id": _uid(), "name": "", "labels": a.get("labels", []),
                 "weight": a.get("weight", 1.0), "actions": [a]}
                for a in alternatives
            ],
        }]
    return list(alternatives)


def build_root(ev: dict) -> tuple[dict | None, str]:
    """Returns (root_action_or_None, human summary)."""
    et = ev["event_type"]

    if et == "single":
        actions = ev.get("actions") or []
        if not actions:
            return None, "empty pool → root=None"
        if len(actions) == 1:
            return actions[0], f"1 action → direct {actions[0]['type']}"
        return {
            "type": "random_group", "id": ev["id"], "labels": [], "weight": 1.0,
            "dedupe": True,
            "options": [
                {"id": _uid(), "name": "", "labels": a.get("labels", []),
                 "weight": a.get("weight", 1.0), "actions": [a]}
                for a in actions
            ],
        }, f"random_group · {len(actions)} options (id=event.id)"

    if et in ("sequence", "beat_sequence"):
        beats = et == "beat_sequence"
        steps = ev.get("beat_sequence_steps" if beats else "sequence_steps") or []
        children = []
        for s in steps:
            children.append({
                "id": _uid(), "name": "", "labels": s.get("labels", []),
                "delay_ms": 0 if beats else s.get("delay_ms", 0),
                "delay_beats": s.get("delay_beats", 0) if beats else 0,
                "pre_ramp": s.get("pre_ramp", True) if beats else True,
                "actions": _step_body(s),
            })
        legacy_rev = ev.get("beat_revert" if beats else "revert")
        revert = None
        if legacy_rev:
            revert = {
                "enabled": legacy_rev.get("enabled", True),
                "delay_ms": 0 if beats else legacy_rev.get("delay_ms", 0),
                "delay_beats": legacy_rev.get("delay_beats", 0) if beats else 0,
                "transition_ms": legacy_rev.get("transition_ms", 500),
                "pre_ramp": legacy_rev.get("pre_ramp", True) if beats else True,
            }
        return {
            "type": "sequence_group", "id": _uid(), "labels": [], "weight": 1.0,
            "timing": "beats" if beats else "ms",
            "children": children, "revert": revert,
            "beat_fallback": ev.get("beat_sequence_fallback", "fallback") if beats else "fallback",
            "start_offset_beats": ev.get("beat_sequence_start_offset_beats", 0) if beats else 0,
        }, (f"sequence_group({'beats' if beats else 'ms'}) · {len(children)} children"
            + (" + revert" if revert else ""))

    if et == "morph_set":
        lanes = ev.get("morph_lanes") or []
        children = []
        for li, lane in enumerate(lanes):
            children.append({
                "id": _uid(), "name": lane.get("name", ""),
                "labels": lane.get("labels", []),
                "offset_ms": int(lane.get("offset_ms") or 0),
                "actions": _wrap_random(lane.get("alternatives") or [],
                                        f"{ev['id']}:lane:{li}"),
            })
        return {
            "type": "parallel_group", "id": _uid(), "labels": [], "weight": 1.0,
            "children": children,
        }, f"parallel_group · {len(children)} lanes"

    if et == "device_settings":
        return {
            "type": "device_settings", "labels": [], "weight": 1.0,
            "targets": ev.get("device_targets") or [],
        }, "device_settings action"

    raise ValueError(f"unexpected type {et}")


def migrate(raw: dict) -> tuple[dict, list[tuple[str, str, str]], int]:
    out: dict = {}
    rows: list[tuple[str, str, str]] = []
    skipped = 0
    for eid, ev in raw.items():
        et = ev.get("event_type", "single")
        if et == "composite" or et in SCENE_TYPES:
            out[eid] = ev
            skipped += 1
            continue
        migrated = dict(ev)
        root, summary = build_root(ev)
        migrated.update(LEGACY_BODY_RESET)
        migrated["event_type"] = "composite"
        migrated["root"] = root
        MusicEvent(**migrated)  # validate — raises on any mapping bug
        out[eid] = migrated
        rows.append((ev.get("name", eid), et, summary))
    return out, rows, skipped


def main() -> int:
    apply = "--apply" in sys.argv
    raw = json.loads(EVENTS_FILE.read_text())
    out, rows, skipped = migrate(raw)

    w = max((len(r[0]) for r in rows), default=10)
    for name, et, summary in rows:
        print(f"{name:<{w}}  {et:<15} → {summary}")
    print(f"\n{len(rows)} events migrate, {skipped} skipped "
          f"(composite/scene-family), all validated via MusicEvent")

    if not apply:
        print("DRY RUN — nothing written. Re-run with --apply to migrate.")
        return 0

    backup = EVENTS_FILE.with_name(
        f"events.json.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(EVENTS_FILE, backup)
    EVENTS_FILE.write_text(json.dumps(out, indent=2))
    print(f"APPLIED. Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
