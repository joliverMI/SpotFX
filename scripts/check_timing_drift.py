#!/usr/bin/env python
"""
Pipeline-drift instrument, demonstrated against real stored lock history.

READ-ONLY: points services/lock_history at the given file and calls
pipeline_drift(), which never writes. Prints the per-session drift table the
Timing page's drift line is built from, plus the current alarm verdict.

  .venv/bin/python scripts/check_timing_drift.py                  # repo storage
  .venv/bin/python scripts/check_timing_drift.py --file /path/to/lock_history.json
  .venv/bin/python scripts/check_timing_drift.py --selftest       # synthetic proof

The instrument exists because of the Aug 25 → Sep 2 2026 incident: the audio
pipeline ratcheted ~350 ms/day to −3.2 s and nothing said so until locks were
failing at the ~3 s search cliff. Against the stored history of that period,
the newest sessions read seconds of drift and alarm; healthy periods read
under ~1 s and stay quiet. --selftest proves both directions synthetically
(no stored file needed) and exits non-zero on failure.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import lock_history  # noqa: E402


def report(path: Path, sessions: int) -> int:
    if not path.exists():
        print(f"no lock history at {path}")
        return 1
    lock_history._STORE_PATH = path
    lock_history._entries = None          # drop any cached copy; re-read the file
    d = lock_history.pipeline_drift(max_sessions=sessions)
    print(f"pipeline drift over {path} — alarm at ±{d['alarm_threshold_ms']}ms, "
          f"sessions need ≥{d['min_baselined']} baselined repeat plays to drive it\n")
    print(f"{'session start (UTC)':>20s} {'plays':>5s} {'baselined':>9s} {'median drift':>12s}")
    for s in reversed(d["sessions"]):     # oldest → newest, reads as a story
        med = s["median_residual_ms"]
        mark = ""
        if med is not None and s["baselined"] >= d["min_baselined"] \
                and abs(med) >= d["alarm_threshold_ms"]:
            mark = "  << past the alarm line"
        print(f"{s['start_at'][:16]:>20s} {s['plays']:>5d} {s['baselined']:>9d} "
              f"{'—' if med is None else f'{med:+d}ms':>12s}{mark}")
    cur = d["current"]
    if cur is None:
        print("\ncurrent: no session with enough baselined repeat plays — nothing to judge")
    else:
        print(f"\ncurrent: {cur['median_residual_ms']:+d}ms over {cur['baselined']} repeat plays "
              f"(session {cur['start_at'][:16]}) → {'ALARM' if d['alarm'] else 'steady'}")
    return 0


def selftest() -> int:
    t0 = datetime(2026, 9, 1, 20, 0, 0, tzinfo=timezone.utc)
    songs = [f"spotify:track:s{i}" for i in range(6)]

    def world(offset_for):
        out = []
        for day in range(10):
            for k, uri in enumerate(songs):
                at = t0 + timedelta(days=day, minutes=4 * k)
                out.append({"at": at.isoformat(), "uri": uri,
                            "offset_ms": offset_for(day, k)})
        out.reverse()                     # store order: newest first
        return out

    failures = 0

    lock_history._entries = world(lambda day, k: 1000 * k)
    d = lock_history.pipeline_drift()
    ok = not d["alarm"] and abs(d["current"]["median_residual_ms"]) < 200
    print(f"steady world stays quiet: {'ok' if ok else 'FAIL'} "
          f"(median {d['current']['median_residual_ms']:+d}ms, alarm={d['alarm']})")
    failures += 0 if ok else 1

    lock_history._entries = world(lambda day, k: 1000 * k - 400 * day)
    d = lock_history.pipeline_drift()
    ok = d["alarm"] and d["current"]["median_residual_ms"] <= -d["alarm_threshold_ms"]
    print(f"−400ms/day ratchet alarms:  {'ok' if ok else 'FAIL'} "
          f"(median {d['current']['median_residual_ms']:+d}ms, alarm={d['alarm']})")
    failures += 0 if ok else 1

    lock_history._entries = None
    return failures


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=Path, default=lock_history._STORE_PATH,
                    help="lock_history.json to read (default: this checkout's storage)")
    ap.add_argument("--sessions", type=int, default=20)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    sys.exit(report(args.file, args.sessions))


if __name__ == "__main__":
    main()
