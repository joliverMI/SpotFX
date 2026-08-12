#!/usr/bin/env python3
"""
Collapse all scene-setting triggers into the single "Intensity Scene" event.

"Intensity Scene" (37b62a98) is an intensity_chooser composite that picks a
scene group by the fired trigger's intensity (Quiet Scenes / Mid Group /
Dark Hype / Bass Drop). Every trigger that used to call a scene-setter
directly — scene groups (Mid Group, Quiet Scenes, Song Start/End pairs),
beat-start composites, standard/chill/relax scene composites, and direct
single-scene fires — is repointed at it. "Mid Morph" (a color+shape update,
not a scene set) is repointed at the fixed "Update Scene" instead.

The canonical trigger vocabulary after this migration:

    Intensity Scene · Update Scene · Shape/Color/Combo Flare ·
    Charge · Lull · Drop

ai_exposed is handed over wholesale: exactly the canon events above are
exposed to the AI/training catalog; every other event is unexposed (custom
events remain fireable/placeable manually, they just stop being training
vocabulary).

Trigger stores rewritten (same set as migrate_quiet_scene_groups.py):
  storage/profiles/*.json            triggers[] + setlist_triggers{}[]
  storage/analyzed_triggers/*.json   embedded-pipeline cache
  storage/training_profiles.json     *_event_id role slots
  storage/triggerless_profiles.json  timed scene / start / end fires
  storage/palettes.json              keyboard palette key bindings

Event BODIES are never rewritten: Intensity Scene's own chooser refs the
scene groups (Quiet/Mid/Dark Hype/Bass Drop) — those must keep working.

Usage
-----
    python3 scripts/migrate_intensity_scene.py            # dry run
    python3 scripts/migrate_intensity_scene.py --apply    # write + backup
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
FIXED_OVERRIDES_FILE = STORAGE / "fixed_event_overrides.json"
BACKUP_DIR = STORAGE / "backups"

INTENSITY_SCENE = "37b62a98-3544-4157-a444-ac605b146039"
UPDATE_SCENE = "fixed-update-scene"

# scene-setting trigger targets -> Intensity Scene
TO_INTENSITY = [
    "86e34a4c-6e80-44e8-b6f7-0691f8087622",  # Mid Group (scene_group)
    "11a6386d-bae0-4646-a69f-ea642e2a6d98",  # Quiet Scenes (scene_group)
    "1cf90ea0-970c-4c30-84c2-1c2dbeb063aa",  # Song Start Scenes- Mid
    "780c711d-4a31-4944-9cb2-5f4c4d361182",  # Song End Scenes- Mid
    "e5bf69f7-663e-4023-9370-fbd45d67932c",  # Song Start Scenes- EDM
    "e711e046-d6b7-4600-b2e1-3a143f692a16",  # Song End Scenes - EDM
    "fd0d1680-4329-4456-9d96-f872dca43bc8",  # Beat Start Scenes - EDM
    "4532ad4f-3579-42fc-a876-6160e6b96699",  # Mid Beat Start
    "f3995e8d-6d18-4648-ba96-7406529cf48d",  # High Energy Relax Scenes - EDM
    "7d38bc33-91d5-4b6b-9d7e-abaf172513cf",  # Standard Scene - EDM
    "608a9744-c11a-4435-b425-f24f3ac9bbf1",  # Chill Scenes
    "c4508681-eb16-4e29-8ceb-69b6a3e6051d",  # Mid Scenes
    "9177cc67-3b02-4d7d-8cd4-adb21a719ae3",  # Lines (scene_update)
    "591c0b32-a607-4f3e-b53b-cc678cecc45f",  # Power Star (scene_update)
    "aad77893-a56e-403f-8331-2bb5f8ae7149",  # Hype Star (scene_update)
    "1abe0083-d7d1-5fdf-b5ce-fb9a16954190",  # Orbits (scene_update)
    "ce69ee8d-5548-42db-85df-48d0149a0087",  # Black Hole (scene_update)
]
REMAP = {eid: INTENSITY_SCENE for eid in TO_INTENSITY}
REMAP["89d32ac8-5692-4ffc-94ea-ed07cc9ac646"] = UPDATE_SCENE  # Mid Morph

# canon = the only ai_exposed vocabulary after this migration
# built-in (code-defined) canon events — exposed via the fixed-overrides
# store, since they never live in events.json
CANON_FIXED = [
    "fixed-update-scene", "fixed-shape-flare", "fixed-color-flare",
    "fixed-combo-flare", "fixed-charge", "fixed-lull", "fixed-drop",
]


def remap_triggers(rows: list) -> int:
    n = 0
    for row in rows:
        if isinstance(row, dict) and row.get("event_id") in REMAP:
            row["event_id"] = REMAP[row["event_id"]]
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry run)")
    args = ap.parse_args()

    events = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    names = {eid: e.get("name", eid) for eid, e in events.items()}
    isc = events.get(INTENSITY_SCENE)
    if not isc:
        print("ERROR: Intensity Scene event not found", file=sys.stderr)
        return 1
    missing = [eid for eid in REMAP if eid not in events]
    if missing:
        print(f"ERROR: remap sources missing from events.json: {missing}",
              file=sys.stderr)
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    hits = Counter()

    canon_ids = {INTENSITY_SCENE}
    print("canon events (ai_exposed=True): Intensity Scene + "
          + ", ".join(CANON_FIXED))
    fixed_overrides = (
        json.loads(FIXED_OVERRIDES_FILE.read_text(encoding="utf-8"))
        if FIXED_OVERRIDES_FILE.exists() else {}
    )
    for eid in CANON_FIXED:
        over = fixed_overrides.setdefault(eid, {})
        if not over.get("ai_exposed"):
            over["ai_exposed"] = True
            hits["fixed_overrides"] += 1
            print(f"fixed override: {eid} ai_exposed -> True")
    names.update({eid: eid.replace("fixed-", "").replace("-", " ").title()
                  for eid in CANON_FIXED})

    # ── 1. events.json: hand the AI/training catalog to the canon ──────────
    for eid, ev in events.items():
        want = eid in canon_ids
        if bool(ev.get("ai_exposed")) != want:
            ev["ai_exposed"] = want
            hits["ai_exposed"] += 1
            print(f"ai_exposed: {names.get(eid)!r} -> {want}")
            MusicEvent(**ev)

    # ── 2. profiles ─────────────────────────────────────────────────────────
    changed_profiles: list[tuple[Path, dict]] = []
    per_target = Counter()
    for path in sorted(PROFILES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("triggers") or []
        for row in rows:
            if isinstance(row, dict) and row.get("event_id") in REMAP:
                per_target[row["event_id"]] += 1
        n = remap_triggers(rows)
        for srows in (data.get("setlist_triggers") or {}).values():
            n += remap_triggers(srows or [])
        if n:
            SongProfile(**data)
            changed_profiles.append((path, data))
            hits["profile_triggers"] += n
    print(f"\nprofiles: {hits['profile_triggers']} triggers in "
          f"{len(changed_profiles)} files")
    for eid, n in per_target.most_common():
        arrow = "Update Scene" if REMAP[eid] == UPDATE_SCENE else "Intensity Scene"
        print(f"  {n:>5}  {names.get(eid)!r} -> {arrow}")

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

    # ── 4/5. training + triggerless role slots ──────────────────────────────
    training = json.loads(TRAINING_FILE.read_text(encoding="utf-8"))
    for pid, prof in training.items():
        for key, val in list(prof.items()):
            if key.endswith("_event_id") and val in REMAP:
                prof[key] = REMAP[val]
                hits["training"] += 1
                print(f"training {prof.get('name', pid)!r}: {key} "
                      f"{names.get(val)!r} -> {names.get(REMAP[val])!r}")

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
    tag = f"intensityscene-{stamp}"
    shutil.copy2(EVENTS_FILE, BACKUP_DIR / f"events.json.bak-{tag}")
    shutil.copy2(TRAINING_FILE, BACKUP_DIR / f"training_profiles.json.bak-{tag}")
    shutil.copy2(PALETTES_FILE, BACKUP_DIR / f"palettes.json.bak-{tag}")
    shutil.copy2(TRIGGERLESS_FILE, BACKUP_DIR / f"triggerless_profiles.json.bak-{tag}")
    if FIXED_OVERRIDES_FILE.exists():
        shutil.copy2(FIXED_OVERRIDES_FILE,
                     BACKUP_DIR / f"fixed_event_overrides.json.bak-{tag}")
    shutil.copytree(PROFILES_DIR, BACKUP_DIR / f"profiles-pre{tag}")
    shutil.copytree(ANALYZED_DIR, BACKUP_DIR / f"analyzed-pre{tag}")
    print(f"\nbackups -> {BACKUP_DIR}/*{tag}*")

    def write(path: Path, data) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)

    write(EVENTS_FILE, events)
    write(FIXED_OVERRIDES_FILE, fixed_overrides)
    write(TRAINING_FILE, training)
    write(PALETTES_FILE, palettes)
    write(TRIGGERLESS_FILE, triggerless)
    for path, data in changed_profiles + changed_analyzed:
        write(path, data)
    print(f"wrote events.json, training_profiles.json, palettes.json, "
          f"triggerless_profiles.json, {len(changed_profiles)} profiles, "
          f"{len(changed_analyzed)} caches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
