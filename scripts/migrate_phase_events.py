"""Repoint song-profile triggers from the genre-flavored charge/lull/drop
events to the fixed phase events (fixed-charge / fixed-lull / fixed-drop).

The old events fired genre scene picks (e.g. "Bass Drop Sequence" is a
random_group of refs to the "Drop" scene group); the fixed events supersede
them: LedFX phase choreography + the active scene's Charge/Lull/Drop lanes,
with Drop's scene-group fallback covering the old switch behavior.

Deliberately NOT remapped: triggers firing general-purpose scene groups
(Mid Group, Dark Hype) that some triggerless genre slots use as charge-ish
moments, and the training-profile slot pointers themselves.

Dry-run by default; --apply writes (atomic tmp+replace, ensure_ascii to match
the app's serializer). Idempotent — already-migrated triggers are skipped.
A tagged backup (storage/backups/profiles-pre-phase-events-*) should exist
before --apply; this script refuses to apply without one.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
from collections import Counter

PROFILES = os.path.join(os.path.dirname(__file__), "..", "storage", "profiles")
BACKUPS = os.path.join(os.path.dirname(__file__), "..", "storage", "backups")

MAPPING = {
    # charge
    "201e7c4f-88d9-46e4-855e-3bcf93ecefd0": "fixed-charge",  # EDM Charge Scenes
    "dd0354f5-e4ac-4aa1-a17a-166a46cd0a13": "fixed-charge",  # Mid Charge Scenes
    "6efa0bcd-f4c8-404f-9d22-ba2bd594624b": "fixed-charge",  # Country Charge Scenes
    # lull
    "7264b514-fe81-4a39-904f-13eef5c93216": "fixed-lull",    # Lull Event - EDM
    "435f7783-9530-43f9-b60d-7dd0efa77e43": "fixed-lull",    # Lull Event - Rock
    "c57a0135-d58a-400d-bbdb-af83ca1dc952": "fixed-lull",    # Lull Event - Trap
    # drop
    "de8b053e-397b-410d-97d0-2f19cacc8ad0": "fixed-drop",    # Bass Drop Sequence
    "c5c81de8-8712-423e-b837-3a1a80bf6228": "fixed-drop",    # Trap Drop Scenes
    "8f825849-ab4d-4f2a-a9fe-7d8960501e08": "fixed-drop",    # Rock Drop Scenes
    "235b76bd-c733-46fa-8868-35fb896a83d7": "fixed-drop",    # Bass Drop Scenes
    "e669da41-9781-4788-96a0-84dd2513f40f": "fixed-drop",    # Bass Drop Morph
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes")
    args = ap.parse_args()

    if args.apply and not glob.glob(
        os.path.join(BACKUPS, "profiles-pre-phase-events-*")
    ):
        print("refusing --apply: no profiles-pre-phase-events-* backup found")
        return 1

    per_target: Counter = Counter()
    touched_files = 0
    total = 0
    for path in sorted(glob.glob(os.path.join(PROFILES, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        changed = 0
        for trig in data.get("triggers", []):
            new = MAPPING.get(trig.get("event_id") or "")
            if new:
                trig["event_id"] = new
                per_target[new] += 1
                changed += 1
            # Charge/Lull triggers ride Override Blend: the phase ramp
            # stretches to the gap to the next trigger, so the build maxes
            # exactly when the lull/drop lands (trigger_engine
            # _phase_blend_ramp_ms). Drop stays a snap — no blend.
            if trig.get("event_id") in ("fixed-charge", "fixed-lull") and not trig.get("override_blend"):
                trig["override_blend"] = True
                per_target["override_blend on"] += 1
                changed += 1
        if changed:
            touched_files += 1
            total += changed
            if args.apply:
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, ensure_ascii=True)
                os.replace(tmp, path)

    mode = "APPLIED" if args.apply else "DRY RUN (use --apply to write)"
    print(f"{mode}: {total} trigger(s) in {touched_files} profile(s)")
    for target, n in per_target.most_common():
        print(f"  {n:5d} → {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
