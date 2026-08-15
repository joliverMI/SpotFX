#!/usr/bin/env python3
"""Migrate legacy MusicTrigger placements into SPECTRA SpectraTrigger
objects, using the mapping ledger in spectra.services.legacy_trigger_migration.

DRY-RUN by default (prints the summary, writes nothing). --apply writes
every MAPPED trigger — flare/charge/lull/drop, scene-change (his ruling:
Option B, fire_scene with scene_id=None; "drop scene" triggers get
intensity forced to MAX), AND update (his correction: fire_scene_update,
one behaviour for both update and reset — see spectra.services.
scene_response.ResponseEngine.on_update) — through spectra.services.
trigger_store.upsert, atomic and idempotent (legacy trigger id reused as
the SpectraTrigger id, so re-running never duplicates).

One category is NEVER written, in either mode, regardless of --apply:
  - RETIRED: Dinner Party Scenes and every trigger that fires it — scrapped
    at his word, out of the migration entirely.

Usage:
    .venv/bin/python scripts/migrate_legacy_triggers.py                     # dry run, real corpus
    .venv/bin/python scripts/migrate_legacy_triggers.py --apply             # write, real corpus
    .venv/bin/python scripts/migrate_legacy_triggers.py --source 'tests/fixtures/profiles/*.json'
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.services.legacy_trigger_migration import migrate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default="storage/profiles/*.json",
                         help="glob of legacy profile JSON files (default: the real corpus)")
    parser.add_argument("--apply", action="store_true",
                         help="write mapped triggers via trigger_store.upsert (default: dry-run)")
    parser.add_argument("--include-setlist", action="store_true",
                         help="also walk setlist_triggers overrides (report.md section 6)")
    args = parser.parse_args()

    summary = migrate(args.source, apply=args.apply, include_setlist=args.include_setlist)

    print(f"source: {args.source}")
    print(f"total triggers seen: {summary.total}")
    print(f"mapped (response + scene-change + update): {summary.mapped}")
    for cls, count in sorted(summary.by_class.items(), key=lambda kv: -kv[1]):
        print(f"  {cls}: {count}")
    if summary.drop_scene_max_intensity:
        print(f"  (of which {summary.drop_scene_max_intensity} are \"drop scenes\" — "
              f"intensity forced to MAX, not their recorded value)")
    print(f"RETIRED (Dinner Party Scenes — scrapped at his word, never written): "
          f"{summary.retired}")
    if summary.invalid_timestamp:
        print(f"INVALID timestamp_ms < 0 in the real source data (never written): "
              f"{summary.invalid_timestamp}  examples={summary.invalid_timestamp_examples}")
    if summary.unclassified:
        print(f"UNCLASSIFIED (event_id not in the ledger — not guessed, not written): "
              f"{summary.unclassified}  ids={sorted(summary.unclassified_ids)}")
    if args.apply:
        print(f"written to storage/spectra/triggers.json: {summary.written}")
    else:
        print("dry run — nothing written. Re-run with --apply to write the mapped "
              "triggers (retired stays excluded either way).")
    return 1 if summary.unclassified else 0


if __name__ == "__main__":
    raise SystemExit(main())
