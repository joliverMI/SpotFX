#!/usr/bin/env python3
"""Import ANALYSED (generated) triggers for every song that has NO authored
triggers yet — the Admiral's follow-up to the authored migration
(scripts/migrate_legacy_triggers.py, PR #57): "not every song has authored
triggers from spotfx, but they should all have analysed triggers that can
be imported."

Analysed triggers are not a separate store — they are front 3's mid-song
generation pass (spectra.services.midsong_generator.generate_for_song,
spectra/models/trigger.py's own binding decision: "ONE mechanism, not
two"), the exact function POST /api/triggers/generate?uri= calls. This
script calls that SAME function directly rather than through the live HTTP
endpoint: generate_for_song does one spectra.services.trigger_store.upsert
per section boundary, and each upsert is a full read+rewrite of
storage/spectra/triggers.json (measured ~126ms per call against the real
11k-trigger corpus) — looping that synchronously inside an async FastAPI
handler would block the SPECTRA process's event loop (bridge polling,
trigger firing, WS ticks) for the whole run. A separate offline process
pays the same per-write cost without stalling the live room, the same
shape scripts/migrate_legacy_triggers.py already used for the authored
corpus.

Target set = every song with usable librosa analysis (analysis_reader.
sections_for_uri, i.e. a real .librosa.json with non-empty sections) MINUS
every song that has at least one source="authored" trigger already —
never the "rest by assumption": a song can already carry generated
triggers from an earlier partial run and still be in scope for a refresh
(generate_for_song is add/update/delete idempotent per its own docstring),
and this script never re-derives that boundary from a stale snapshot — it
recomputes both sets fresh against storage on every run.

A song already holding at least one authored trigger is NEVER touched:
generate_for_song's own contract never writes to a song's authored
triggers (only source="generated" entries keyed by generator_key), and
this script additionally asserts result["skipped_authored"] == 0 for
every target song and HALTS on violation — a song this script expected to
have zero authored triggers turning out to have one is exactly the kind of
discrepancy CLAUDE.md's task discipline says to stop and reconcile against
real data, not reason past.

DRY-RUN by default (prints the projected moment counts per song, writes
nothing). --apply writes via trigger_store.upsert (atomic, idempotent —
safe to interrupt and re-run; already-generated songs report added=0 on a
repeat pass). --limit caps how many target songs are processed, for a
staged/observable rollout. --uri restricts to one song (repeatable).

Usage:
    .venv/bin/python scripts/import_analysed_triggers.py                # dry run, real corpus
    .venv/bin/python scripts/import_analysed_triggers.py --apply         # write, real corpus
    .venv/bin/python scripts/import_analysed_triggers.py --apply --limit 5
    .venv/bin/python scripts/import_analysed_triggers.py --apply --uri spotify:track:XXXX
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import spectra  # noqa: F401  already importable (e.g. PYTHONPATH points at the target checkout)
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra import config  # noqa: E402
from spectra.services import analysis_reader, midsong_generator  # noqa: E402


def analyzable_uris() -> set[str]:
    """Every song with a usable (non-empty) librosa section list — the
    same definition analysis_reader.sections_for_uri itself applies."""
    analysis_reader._build_index()  # rebuild fresh, don't trust a stale index
    out: set[str] = set()
    for uri in analysis_reader._shape_index:
        if analysis_reader.sections_for_uri(uri):
            out.add(uri)
    return out


def songs_with_authored_trigger() -> set[str]:
    """Raw read of storage/spectra/triggers.json — deliberately not routed
    through trigger_store.list_for_song (which pydantic-validates every
    trigger on every song just to classify one field); a plain scan is
    read-only and cheap for a corpus this size."""
    if not config.TRIGGERS_FILE.exists():
        return set()
    raw = json.loads(config.TRIGGERS_FILE.read_text(encoding="utf-8"))
    return {uri for uri, triggers in raw.items()
            if any(t.get("source") == "authored" for t in triggers)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                         help="write via midsong_generator.generate_for_song (default: dry-run)")
    parser.add_argument("--limit", type=int, default=None,
                         help="process at most N target songs")
    parser.add_argument("--uri", action="append", default=None,
                         help="restrict to this song URI (repeatable); still must be in the target set")
    parser.add_argument("--gained-report", type=Path, default=None,
                         help="write the list of songs that gained coverage (added>0) to this JSON path")
    args = parser.parse_args()

    analyzable = analyzable_uris()
    authored = songs_with_authored_trigger()
    target = sorted(analyzable - authored)
    if args.uri:
        wanted = set(args.uri)
        missing = wanted - set(target)
        if missing:
            print(f"REFUSING: --uri value(s) not in the target set (already authored, "
                  f"or no usable analysis): {sorted(missing)}")
            return 1
        target = [u for u in target if u in wanted]
    if args.limit is not None:
        target = target[:args.limit]

    print(f"analyzable songs (usable librosa sections): {len(analyzable)}")
    print(f"songs with >=1 authored trigger (protected, never touched): {len(authored)}")
    print(f"target songs (analyzable, zero authored): {len(analyzable - authored)}")
    print(f"processing this run: {len(target)}")
    print()

    t0 = time.time()
    gained_coverage: list[str] = []  # zero generated before -> >0 generated after
    totals = {"moments": 0, "added": 0, "updated": 0, "deleted": 0}
    zero_moment_songs: list[str] = []

    for i, uri in enumerate(target, 1):
        if not args.apply:
            moments = midsong_generator.candidate_moments(uri)
            totals["moments"] += len(moments)
            if not moments:
                zero_moment_songs.append(uri)
            continue

        result = midsong_generator.generate_for_song(uri)
        if result["skipped_authored"] != 0:
            print(f"HALT: {uri} reports skipped_authored={result['skipped_authored']} "
                  f"but was selected as zero-authored — storage disagrees with this "
                  f"script's own snapshot. Stopping without further writes.")
            return 2
        for k in ("moments", "added", "updated", "deleted"):
            totals[k] += result[k]
        if result["moments"] == 0:
            zero_moment_songs.append(uri)
        if result["added"] > 0:
            gained_coverage.append(uri)
        if i % 25 == 0 or i == len(target):
            elapsed = time.time() - t0
            print(f"  [{i}/{len(target)}] {elapsed:.0f}s elapsed, "
                  f"+{totals['added']} generated triggers so far")

    elapsed = time.time() - t0
    print()
    print(f"elapsed: {elapsed:.1f}s")
    print(f"songs with zero librosa sections at generation time (no-op): {len(zero_moment_songs)}")
    print(f"total moments seen: {totals['moments']}")
    if args.apply:
        print(f"generated triggers added: {totals['added']}")
        print(f"generated triggers updated: {totals['updated']}")
        print(f"generated triggers deleted (stale boundary): {totals['deleted']}")
        print(f"songs that gained coverage (added>0): {len(gained_coverage)}")
        if args.gained_report:
            args.gained_report.write_text(json.dumps(sorted(gained_coverage), indent=2))
            print(f"wrote gained-coverage list to {args.gained_report}")
    else:
        print("dry run — nothing written. Re-run with --apply to write.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
