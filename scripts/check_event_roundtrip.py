"""Round-trip invariant check for the React event editor (web/).

Compares editor-serialized events against the stored originals, normalizing both
through the pydantic MusicEvent model so default-field noise doesn't count as a
diff. Any difference on an *unedited* event is an editor serializer bug.

Usage:
    .venv/bin/python scripts/check_event_roundtrip.py <editor_dump.json>

where <editor_dump.json> is a {event_id: serialized_event} map produced by the
editor's load→serialize path (see the node dump script in the web/ workflow),
or omit the argument to self-check storage/events.json against pydantic alone.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.music_event import MusicEvent  # noqa: E402

STORAGE = Path(__file__).resolve().parent.parent / "storage" / "events.json"


def normalize(raw: dict) -> dict:
    return MusicEvent(**raw).model_dump(mode="json")


def main() -> int:
    stored = json.loads(STORAGE.read_text())
    dump = json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv) > 1 else None

    bad = 0
    for eid, raw in stored.items():
        try:
            base = normalize(raw)
        except Exception as e:
            print(f"✗ stored event {raw.get('name', eid)} fails model parse: {e}")
            bad += 1
            continue
        if dump is None:
            continue
        if eid not in dump:
            print(f"~ {raw.get('name', eid)}: missing from editor dump (fixed events are expected here)")
            continue
        try:
            ours = normalize(dump[eid])
        except Exception as e:
            print(f"✗ editor output for {raw.get('name', eid)} fails model parse: {e}")
            bad += 1
            continue
        if ours != base:
            bad += 1
            diff_keys = [k for k in base if base.get(k) != ours.get(k)]
            print(f"✗ {raw.get('name', eid)}: round-trip diff in {diff_keys}")

    n = len(stored)
    print(f"checked {n} stored events{' + editor dump' if dump else ''}; problems: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
