"""
SpotFX — One-time migration script.

Task A: Add pre_brightness / pre_transition defaults to all single events.
  - Events with "Scenes" in their name: both enabled (True)
  - All other single events: both disabled (False)
  - Values default to 1.0 (brightness) and 0.5s (transition)

Task B: Delete sequence "wrapper" events and update profile trigger references.
  - A wrapper is a sequence event with exactly one sequence_step that is a
    step_type="event" reference to a Scenes event.
  - All song profiles that reference a wrapper are updated to point directly
    to the underlying Scenes event instead.

Run from the project root:
    python scripts/migrate_events.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

BASE_DIR    = Path(__file__).parent.parent
EVENTS_FILE = BASE_DIR / "storage" / "events.json"
PROFILES_DIR = BASE_DIR / "storage" / "profiles"


def main() -> None:
    if not EVENTS_FILE.exists():
        print("ERROR: storage/events.json not found. Run from project root.")
        sys.exit(1)

    events: dict = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))

    # ── Task A: pre_brightness / pre_transition defaults ──────────────────────
    task_a_updated = 0
    for event in events.values():
        if event.get("event_type") != "single":
            continue
        has_scenes = "Scenes" in event.get("name", "")
        event.setdefault("pre_brightness_value", 1.0)
        event.setdefault("pre_transition_value", 0.5)
        event["pre_brightness_enabled"] = has_scenes
        event["pre_transition_enabled"] = has_scenes
        task_a_updated += 1

    print(f"Task A: updated {task_a_updated} single events with pre-command defaults.")

    # ── Task B: find wrapper sequences and build replacement map ─────────────
    # Wrapper: sequence with exactly one step_type="event" step referencing a Scenes event
    replacements: dict[str, str] = {}  # old_seq_id -> scenes_event_id
    for eid, event in events.items():
        if event.get("event_type") != "sequence":
            continue
        steps = event.get("sequence_steps", [])
        if len(steps) != 1:
            continue
        step = steps[0]
        if step.get("step_type") != "event":
            continue
        target_id = step.get("event_id", "")
        target = events.get(target_id)
        if target and "Scenes" in target.get("name", ""):
            replacements[eid] = target_id
            print(f"  Wrapper found: '{event['name']}' ({eid[:8]}...) -> '{target['name']}' ({target_id[:8]}...)")

    if not replacements:
        print("Task B: no wrapper sequences found.")
    else:
        print(f"Task B: {len(replacements)} wrapper(s) identified.")

    # ── Task B: update profile trigger references ─────────────────────────────
    profiles_changed = 0
    triggers_updated = 0
    for profile_path in sorted(PROFILES_DIR.glob("*.json")):
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  WARNING: could not read {profile_path.name}: {exc}")
            continue
        changed = False
        for trigger in profile.get("triggers", []):
            old_id = trigger.get("event_id", "")
            if old_id in replacements:
                new_id = replacements[old_id]
                trigger["event_id"] = new_id
                triggers_updated += 1
                changed = True
        if changed:
            profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
            profiles_changed += 1

    print(f"Task B: updated {triggers_updated} trigger(s) across {profiles_changed} profile(s).")

    # ── Task B: delete wrapper events ─────────────────────────────────────────
    for eid in replacements:
        del events[eid]
    print(f"Task B: deleted {len(replacements)} wrapper event(s) from events.json.")

    # ── Save events.json ──────────────────────────────────────────────────────
    EVENTS_FILE.write_text(json.dumps(events, indent=2), encoding="utf-8")
    print("Done. events.json saved.")


if __name__ == "__main__":
    main()
