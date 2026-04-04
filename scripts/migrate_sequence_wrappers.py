"""
One-shot migration: create sequence wrapper events for the 11 "Scenes" events,
then update all profile trigger references to point to the new wrappers.

Run from the SpotFX project root:
    python scripts/migrate_sequence_wrappers.py
"""
from __future__ import annotations
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent
EVENTS_FILE = ROOT / "storage" / "events.json"
PROFILES_DIR = ROOT / "storage" / "profiles"

# Old event ID → new wrapper name (strip "Scenes" from display name)
WRAPPERS = [
    ("e5bf69f7-663e-4023-9370-fbd45d67932c", "Song Start - EDM"),
    ("fd0d1680-4329-4456-9d96-f872dca43bc8", "Bass Beat Start"),
    ("e711e046-d6b7-4600-b2e1-3a143f692a16", "Song End - EDM"),
    ("de8b053e-397b-410d-97d0-2f19cacc8ad0", "Bass Drop"),
    ("201e7c4f-88d9-46e4-855e-3bcf93ecefd0", "EDM Charge"),
    ("40e0efeb-fb09-4757-82ae-ebdbc21db1ce", "Quiet - EDM"),
    ("f3995e8d-6d18-4648-ba96-7406529cf48d", "High Energy Relax - EDM"),
    ("1cf90ea0-970c-4c30-84c2-1c2dbeb063aa", "Song Start - Mid"),
    ("780c711d-4a31-4944-9cb2-5f4c4d361182", "Song End - Mid"),
    ("dd0354f5-e4ac-4aa1-a17a-166a46cd0a13", "Mid Charge"),
    ("c4508681-eb16-4e29-8ceb-69b6a3e6051d", "Mid Shift"),
]


def main() -> None:
    events: dict = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))

    # Build old→new mapping and create wrapper events
    old_to_new: dict[str, str] = {}
    created: list[str] = []

    for old_id, new_name in WRAPPERS:
        if old_id not in events:
            print(f"  SKIP: {old_id!r} not found in events.json (already migrated?)")
            continue

        original = events[old_id]
        new_id = str(uuid.uuid4())
        old_to_new[old_id] = new_id

        wrapper = {
            "id": new_id,
            "name": new_name,
            "event_type": "sequence",
            "color": original.get("color", "#FFD700"),
            "labels": [],
            "energy_level": None,
            "actions": [],
            "sequence_steps": [
                {"step_type": "event", "event_id": old_id, "delay_ms": 0, "labels": []}
            ],
        }
        events[new_id] = wrapper
        created.append(f"  {new_name!r} ({new_id}) wraps {old_id}")

    EVENTS_FILE.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"events.json: added {len(created)} wrapper(s):")
    for line in created:
        print(line)

    if not old_to_new:
        print("No wrappers created — nothing to migrate in profiles.")
        return

    # Update profile trigger references
    profile_files = list(PROFILES_DIR.glob("*.json"))
    updated_count = 0
    for pf in profile_files:
        data = json.loads(pf.read_text(encoding="utf-8"))
        changed = False
        for trigger in data.get("triggers", []):
            if trigger.get("event_id") in old_to_new:
                trigger["event_id"] = old_to_new[trigger["event_id"]]
                changed = True
        if changed:
            pf.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            updated_count += 1

    print(f"profiles: updated {updated_count} file(s) of {len(profile_files)} total.")
    print("Migration complete.")


if __name__ == "__main__":
    main()
