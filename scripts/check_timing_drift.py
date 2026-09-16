#!/usr/bin/env python
"""
Pipeline-drift instrument, demonstrated against real stored lock history.

READ-ONLY: points services/lock_history at the given file and calls
pipeline_drift(), which never writes. Prints the per-session drift table the
Timing page's drift line is built from, plus the current alarm verdict.

  .venv/bin/python scripts/check_timing_drift.py                  # repo storage
  .venv/bin/python scripts/check_timing_drift.py --file /path/to/lock_history.json
  .venv/bin/python scripts/check_timing_drift.py --file /copy/lock_history.json \
      --anchors /copy/lock_history_anchors.json
  .venv/bin/python scripts/check_timing_drift.py --selftest       # synthetic proof

A READ-ONLY COPY NEEDS BOTH FILES. The level is measured against per-song
anchors kept in a sidecar store beside the log — `<log stem>_anchors.json`
(storage/lock_history_anchors.json for the live log) — because the capped
log itself drops the plays those anchors came from. Copy the sidecar next
to the log copy under that name, or pass --anchors. A log whose anchors
store was already written never rebuilds it, so a copy of the log alone
reports no level; the report says so and exits 2 rather than showing an
empty level column as if it were a reading.

The era never moves on its own. Adopting a new one is a person's explicit,
audited act: preview with GET /api/lock-history/drift/reanchor-preview, then
POST /api/lock-history/drift/reanchor with start_at, by, reason and
confirm: true (services/lock_history.reanchor). The report prints the latest
re-anchor it finds in the store.

The instrument exists because of the Aug 25 → Sep 2 2026 incident: the audio
pipeline ratcheted ~350 ms/day to −3.2 s and nothing said so until locks were
failing at the ~3 s search cliff. Against the stored history of that period,
the newest sessions read seconds of drift and alarm; healthy periods read
under ~1 s and stay quiet. --selftest proves both directions synthetically
(no stored file needed) and exits non-zero on failure.

Rebuilt 2026-09 (data/spectra-timing-drift-cause/report.md): the table now
leads with LEVEL — each play's winning offset vs that song's own FIXED,
quality-gated anchor — plus a per-session ramp/step/stable `shape`, instead
of only the legacy sliding-baseline residual, which reads recent CHANGE
rather than level and turned a real ramp-then-step into "scatter" twice.

WHAT HIS REAL HISTORY READS AS: RAMP-THEN-STEP. Run 2026-09-16 against a
read-only copy of the live log (500 plays, Aug 28 → Sep 16; no anchors store
written yet, so the era was derived from the log as it stood: Aug 28 → Sep 1,
75 anchored songs): −1384 start (Sep 3), then ramp −1612, −2596, −3061,
−3187 (Sep 11 00:04, within the 200 ms band of the session before it, so
tagged stable), ramp −3554 (Sep 11 22:40), then STEP to +1460 over 17
counted plays (Sep 13 21:06). No scatter, no sign flips. There is no
"stable" reading AFTER the step, and that is the data, not the classifier:
the step itself landed inside the Sep 11 22:40 session two plays before it
ended (so that session still reads ramp), the Sep 13 01:36 evening holds a
single counted play and is correctly "insufficient", and no qualifying
session follows Sep 13 21:06 yet. The originally stated bar —
ramp-then-step-then-STABLE — was wrong about his data; the synthetic
tests/test_lock_history_drift.py world that has all three phases proves
the classifier's logic, not this history. While no store is written the
log's oldest plays keep evicting, so re-running this later can shift these
numbers a little.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import lock_history  # noqa: E402


def report(path: Path, sessions: int, anchors: Optional[Path] = None) -> int:
    if not path.exists():
        print(f"no lock history at {path}")
        return 1
    if anchors is not None and not anchors.exists():
        print(f"no anchors store at {anchors}")
        return 1
    lock_history._STORE_PATH = path
    lock_history._entries = None          # drop any cached copy; re-read the file
    anchors_path = anchors if anchors is not None else lock_history._anchor_path()
    derived_anchor_path = lock_history._anchor_path
    lock_history._anchor_path = lambda: anchors_path
    try:
        d = lock_history.pipeline_drift(max_sessions=sessions)
    finally:
        lock_history._anchor_path = derived_anchor_path
    print(f"pipeline drift over {path} — alarm at ±{d['alarm_threshold_ms']}ms, "
          f"sessions need ≥{d['min_baselined']} gated plays to drive it")
    persisted_at = lock_history._anchors_persisted_at
    missing_store = not anchors_path.exists()
    print(f"anchors store: {anchors_path} ({'not found' if missing_store else 'found'})")
    if missing_store and persisted_at is not None:
        print(f"  !! this log's anchors store was already written ({persisted_at[:16]}), and "
              f"it is not beside this log. Copy the live storage/lock_history_anchors.json "
              f"to {anchors_path} or pass --anchors; a copy of the log alone cannot "
              f"reproduce the level.")
    elif missing_store and d["anchor_status"] == "save_pending":
        print("  this log's anchors store has not been written yet and the log has evicted "
              "plays since the last attempt — the next recorded play retries the write")
    elif missing_store:
        print("  this log has never had an anchors store written — the era is derived "
              "from the log as it stands")
    era = d["anchor_era"]
    print(f"anchor era: none — no song has an anchor ({d['anchor_status']})" if era is None else
          f"anchor era: {era['start_at'][:16]} → {era['end_at'][:16]} ({era['songs']} anchored songs)")
    if d["anchor_samples_unsaved"]:
        print(f"  !! {d['anchor_samples_unsaved']} anchor-era play(s) not saved into the anchors "
              f"store ({d['anchor_status']})")
    if era is not None and era["last_reanchor"] is not None:
        ev = era["last_reanchor"]
        print(f"  re-anchored {era['reanchors']}×, latest {ev['at'][:16]} by {ev['by']}: {ev['reason']}")
    print()
    print(f"{'session start (UTC)':>20s} {'plays':>5s} {'lvl n':>5s} {'LEVEL':>9s} "
          f"{'shape':>12s}  |  {'old n':>5s} {'old resid':>10s}")
    for s in reversed(d["sessions"]):     # oldest → newest, reads as a story
        lvl, old = s["level_ms"], s["median_residual_ms"]
        mark = "  << past the alarm line" if (
            lvl is not None and s["level_baselined"] >= d["min_baselined"]
            and abs(lvl) >= d["alarm_threshold_ms"]) else ""
        print(f"{s['start_at'][:16]:>20s} {s['plays']:>5d} {s['level_baselined']:>5d} "
              f"{'—' if lvl is None else f'{lvl:+d}ms':>9s} {s['shape']:>12s}  |  "
              f"{s['baselined']:>5d} {'—' if old is None else f'{old:+d}ms':>10s}{mark}")
    cur = d["current"]
    if cur is None:
        print("\ncurrent: no session with enough gated plays — nothing to judge")
    else:
        print(f"\ncurrent: {cur['level_ms']:+d}ms level ({cur['shape']}) over "
              f"{cur['level_baselined']} gated plays (session {cur['start_at'][:16]}) "
              f"→ {'ALARM' if d['alarm'] else 'steady'}")
    return 2 if era is None and missing_store and persisted_at is not None else 0


def selftest() -> int:
    saved = (lock_history._STORE_PATH, lock_history._entries,
             lock_history._anchor_seed_oldest, lock_history._anchors_persisted_at,
             lock_history._anchor_samples_unsaved)
    with tempfile.TemporaryDirectory(prefix="check_timing_drift_") as tmp:
        lock_history._STORE_PATH = Path(tmp) / "lock_history.json"
        lock_history._anchor_seed_oldest = None
        lock_history._anchors_persisted_at = None
        lock_history._anchor_samples_unsaved = []
        try:
            return _selftest_worlds()
        finally:
            (lock_history._STORE_PATH, lock_history._entries,
             lock_history._anchor_seed_oldest, lock_history._anchors_persisted_at,
             lock_history._anchor_samples_unsaved) = saved


def _selftest_worlds() -> int:
    t0 = datetime(2026, 9, 1, 20, 0, 0, tzinfo=timezone.utc)
    songs = [f"spotify:track:s{i}" for i in range(6)]

    def world(offset_for):
        out = []
        for day in range(10):
            for k, uri in enumerate(songs):
                at = t0 + timedelta(days=day, minutes=4 * k)
                out.append({"at": at.isoformat(), "uri": uri,
                            "offset_ms": offset_for(day, k),
                            "locked": True, "quality": 0.9})
        out.reverse()                     # store order: newest first
        return out

    failures = 0

    lock_history._entries = world(lambda day, k: 1000 * k)
    d = lock_history.pipeline_drift()
    ok = not d["alarm"] and abs(d["current"]["level_ms"]) < 200
    print(f"steady world stays quiet: {'ok' if ok else 'FAIL'} "
          f"(level {d['current']['level_ms']:+d}ms, alarm={d['alarm']})")
    failures += 0 if ok else 1

    lock_history._entries = world(lambda day, k: 1000 * k - 400 * day)
    d = lock_history.pipeline_drift()
    ok = d["alarm"] and d["current"]["level_ms"] <= -d["alarm_threshold_ms"]
    print(f"−400ms/day ratchet alarms:  {'ok' if ok else 'FAIL'} "
          f"(level {d['current']['level_ms']:+d}ms, alarm={d['alarm']})")
    failures += 0 if ok else 1
    return failures


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=lock_history._STORE_PATH,
                    help="lock_history.json to read (default: this checkout's storage)")
    ap.add_argument("--anchors", type=Path, default=None,
                    help="its anchors store (default: <file stem>_anchors.json beside --file; "
                         "a copy of the log needs this copied with it)")
    ap.add_argument("--sessions", type=int, default=20)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    sys.exit(report(args.file, args.sessions, args.anchors))


if __name__ == "__main__":
    main()
