#!/usr/bin/env python3
"""
Swap the per-genre "Scenes" composites for scene_group events.

Three edits, all driven off the scene_group "Quiet Scenes" (11a6386d):

  1. Every trigger that fires "Quiet Scenes- Mid" or "Quiet Scenes- EDM"
     (both composites that wrapped the Particles scene_group + a set_color)
     is repointed at the "Quiet Scenes" scene_group itself.

  2. Every trigger that fires "Mid Scenes" is repointed at "Mid Group"
     (the scene_group sibling that already exists).

  3. The four "Song Start / Song End Scenes" events — one pair per genre —
     are converted IN PLACE into copies of the "Quiet Scenes" scene_group.
     In place, because that keeps their ids (no trigger rewrite needed) and
     their names/colors/labels/energy (so the AI generator and the event
     list still see the same four roles). Each keeps its own id, so each
     gets its own rotation cursor — `_select_scene_group_member` keys
     `_scene_cursor` by group id.

Trigger stores rewritten
------------------------
  storage/profiles/*.json            triggers[] + setlist_triggers{}[]
  storage/analyzed_triggers/*.json   embedded-pipeline cache (regenerable,
                                     but remapped so cached plays match)
  storage/training_profiles.json     *_event_id role slots
  storage/palettes.json              live keyboard palette key bindings
  storage/triggerless_profiles.json  timed scene / start / end fires

NOT touched (reported instead): storage/ai_suggestions/ (pending review
queues, incl. provenance ids) and the "Country Charge Scenes" composite,
whose event_ref child fires "Mid Scenes" — an event body, not a trigger.

Usage
-----
    python3 scripts/migrate_quiet_scene_groups.py            # dry run
    python3 scripts/migrate_quiet_scene_groups.py --apply    # write + backup
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from models.music_event import MusicEvent          # noqa: E402
from models.song_profile import SongProfile        # noqa: E402

STORAGE = ROOT / "storage"
EVENTS_FILE = STORAGE / "events.json"
PROFILES_DIR = STORAGE / "profiles"
ANALYZED_DIR = STORAGE / "analyzed_triggers"
TRAINING_FILE = STORAGE / "training_profiles.json"
TRIGGERLESS_FILE = STORAGE / "triggerless_profiles.json"
PALETTES_FILE = STORAGE / "palettes.json"
BACKUP_DIR = STORAGE / "backups"

QUIET_GROUP = "11a6386d-bae0-4646-a69f-ea642e2a6d98"   # scene_group "Quiet Scenes"
MID_GROUP = "86e34a4c-6e80-44e8-b6f7-0691f8087622"     # scene_group "Mid Group"

# old trigger target -> new trigger target
REMAP = {
    "af066833-f371-4077-848d-6589b893c223": QUIET_GROUP,  # Quiet Scenes- Mid
    "40e0efeb-fb09-4757-82ae-ebdbc21db1ce": QUIET_GROUP,  # Quiet Scenes- EDM
    "c4508681-eb16-4e29-8ceb-69b6a3e6051d": MID_GROUP,    # Mid Scenes
}

# events converted in place into copies of QUIET_GROUP
SONG_EDGE_EVENTS = [
    "e5bf69f7-663e-4023-9370-fbd45d67932c",  # Song Start Scenes- EDM
    "e711e046-d6b7-4600-b2e1-3a143f692a16",  # Song End Scenes - EDM
    "1cf90ea0-970c-4c30-84c2-1c2dbeb063aa",  # Song Start Scenes- Mid
    "780c711d-4a31-4944-9cb2-5f4c4d361182",  # Song End Scenes- Mid
]

# Fields the copy takes from the source group. Everything else (id, name,
# color, labels, energy_level, ai_exposed, event_offset_ms, ...) stays.
GROUP_FIELDS = [
    "event_type", "root", "actions", "sequence_steps", "revert",
    "beat_sequence_steps", "beat_revert", "beat_sequence_fallback",
    "beat_sequence_start_offset_beats", "morph_lanes", "device_targets",
    "scene_group_members", "scene_group_mode", "scene_group_cycle_behavior",
    "scene_group_exclude_current", "scene_group_color_ref_id",
]


def remap_triggers(rows: list) -> int:
    """Repoint event_id on a list of trigger dicts. Returns rows changed."""
    n = 0
    for row in rows:
        if isinstance(row, dict) and row.get("event_id") in REMAP:
            row["event_id"] = REMAP[row["event_id"]]
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    events = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    src = events.get(QUIET_GROUP)
    if not src or src.get("event_type") != "scene_group":
        print(f"ERROR: {QUIET_GROUP} is not a scene_group event", file=sys.stderr)
        return 1
    names = {eid: e.get("name", eid) for eid, e in events.items()}

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    hits = Counter()

    # ── 1. events.json: Song Start/End -> copies of the Quiet Scenes group ──
    print("Song Start / Song End events -> copies of 'Quiet Scenes':")
    for eid in SONG_EDGE_EVENTS:
        ev = events.get(eid)
        if ev is None:
            print(f"  MISSING {eid}")
            continue
        was = ev.get("event_type")
        for f in GROUP_FIELDS:
            ev[f] = json.loads(json.dumps(src[f]))  # deep copy
        MusicEvent(**ev)  # validate
        hits["events"] += 1
        print(f"  {ev['name']!r}: {was} -> scene_group "
              f"({len(ev['scene_group_members'])} members, "
              f"{ev['scene_group_cycle_behavior']})")

    # ── 1b. hand the AI catalog over to the groups ──────────────────────────
    # `ai_trigger_service` builds its event catalog from ai_exposed events, so
    # without this the generator keeps placing the composites we just replaced.
    # energy_level is an AI prompt hint only — carry it across too.
    for old, new in REMAP.items():
        if events.get(old, {}).get("ai_exposed"):
            events[old]["ai_exposed"] = False
            hits["ai_exposed"] += 1
            print(f"ai_exposed: {names.get(old)!r} -> False")
        if not events[new].get("ai_exposed"):
            events[new]["ai_exposed"] = True
            hits["ai_exposed"] += 1
            print(f"ai_exposed: {names.get(new)!r} -> True")
        if events[new].get("energy_level") is None:
            events[new]["energy_level"] = events.get(old, {}).get("energy_level")
            print(f"energy_level: {names.get(new)!r} -> "
                  f"{events[new]['energy_level']} (from {names.get(old)!r})")
        MusicEvent(**events[new])

    # ── 2. profiles ─────────────────────────────────────────────────────────
    changed_profiles: list[tuple[Path, dict]] = []
    for path in sorted(PROFILES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        n = remap_triggers(data.get("triggers") or [])
        for rows in (data.get("setlist_triggers") or {}).values():
            n += remap_triggers(rows or [])
        if n:
            SongProfile(**data)  # validate
            changed_profiles.append((path, data))
            hits["profile_triggers"] += n
    print(f"\nprofiles: {hits['profile_triggers']} triggers in "
          f"{len(changed_profiles)} files")

    # ── 3. analyzed-trigger cache ───────────────────────────────────────────
    changed_analyzed: list[tuple[Path, dict]] = []
    for path in sorted(ANALYZED_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        n = remap_triggers(data.get("triggers") or [])
        if n:
            changed_analyzed.append((path, data))
            hits["analyzed"] += n
    print(f"analyzed_triggers: {hits['analyzed']} cached triggers in "
          f"{len(changed_analyzed)} files")

    # ── 4. training profiles (role slots) ───────────────────────────────────
    training = json.loads(TRAINING_FILE.read_text(encoding="utf-8"))
    for pid, prof in training.items():
        for key, val in list(prof.items()):
            if key.endswith("_event_id") and val in REMAP:
                prof[key] = REMAP[val]
                hits["training"] += 1
                print(f"training {prof.get('name', pid)!r}: {key} "
                      f"{names.get(val)!r} -> {names.get(REMAP[val])!r}")

    # ── 5. triggerless profiles (timed scene/start/end fires) ───────────────
    triggerless = json.loads(TRIGGERLESS_FILE.read_text(encoding="utf-8"))
    for pid, prof in triggerless.items():
        for key, val in list(prof.items()):
            if key.endswith("_event_id") and val in REMAP:
                prof[key] = REMAP[val]
                hits["triggerless"] += 1
                print(f"triggerless {prof.get('name', pid)!r}: {key} "
                      f"{names.get(val)!r} -> {names.get(REMAP[val])!r}")

    # ── 6. palette key bindings ─────────────────────────────────────────────
    palettes = json.loads(PALETTES_FILE.read_text(encoding="utf-8"))
    for pal in palettes:
        for key, val in list((pal.get("keys") or {}).items()):
            if val in REMAP:
                pal["keys"][key] = REMAP[val]
                hits["palettes"] += 1
                print(f"palette {pal.get('name')!r}: key {key!r} "
                      f"{names.get(val)!r} -> {names.get(REMAP[val])!r}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    # ── write ───────────────────────────────────────────────────────────────
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EVENTS_FILE, BACKUP_DIR / f"events.json.bak-scenegroup-{stamp}")
    shutil.copy2(TRAINING_FILE, BACKUP_DIR / f"training_profiles.json.bak-scenegroup-{stamp}")
    shutil.copy2(PALETTES_FILE, BACKUP_DIR / f"palettes.json.bak-scenegroup-{stamp}")
    shutil.copy2(TRIGGERLESS_FILE, BACKUP_DIR / f"triggerless_profiles.json.bak-scenegroup-{stamp}")
    shutil.copytree(PROFILES_DIR, BACKUP_DIR / f"profiles-prescenegroup-{stamp}")
    shutil.copytree(ANALYZED_DIR, BACKUP_DIR / f"analyzed-prescenegroup-{stamp}")
    print(f"\nbackups -> {BACKUP_DIR}/*-{stamp}")

    def write(path: Path, data) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)

    write(EVENTS_FILE, events)
    write(TRAINING_FILE, training)
    write(PALETTES_FILE, palettes)
    write(TRIGGERLESS_FILE, triggerless)
    for path, data in changed_profiles + changed_analyzed:
        write(path, data)

    print(f"wrote events.json, training_profiles.json, palettes.json, "
          f"{len(changed_profiles)} profiles, {len(changed_analyzed)} caches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
